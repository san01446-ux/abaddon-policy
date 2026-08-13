from __future__ import annotations

import math
from datetime import date, datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

import discord
from discord.ext import commands

from apocalypse_bot.commands.v37_gambling_experience import KST, _kst_date, _signed


BANK_MIN_AMOUNT = 100
BANK_MAX_TRANSACTION = 100_000_000
BANK_SAVINGS_DAILY_RATE = 0.003       # 0.3%
BANK_LOAN_DAILY_RATE = 0.02           # 2%
LOAN_SHARK_ORIGINATION_RATE = 0.10    # 빌리는 순간 원금에 10% 수수료
LOAN_SHARK_DAILY_RATE = 0.12          # 12%
INTEREST_MAX_OFFLINE_DAYS = 30
FINANCE_HISTORY_LIMIT = 30


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_date(value: Any) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return _utc_now().astimezone(KST).date()


def _days_since(value: Any) -> int:
    today = _utc_now().astimezone(KST).date()
    return max(0, min(INTEREST_MAX_OFFLINE_DAYS, (today - _parse_date(value)).days))


def _compound(principal: int, rate: float, days: int) -> int:
    if principal <= 0 or days <= 0:
        return int(principal)
    return int(math.ceil(principal * ((1.0 + rate) ** days)))


def ensure_finance_profile(user: Dict[str, Any]) -> Dict[str, Any]:
    finance = user.setdefault("finance", {})
    if not isinstance(finance, dict):
        finance = {}
        user["finance"] = finance

    bank = finance.setdefault("bank", {})
    if not isinstance(bank, dict):
        bank = {}
        finance["bank"] = bank
    bank_defaults = {
        "savings": 0,
        "loan_debt": 0,
        "credit_score": 500,
        "last_interest_date": _kst_date(),
        "total_deposited": 0,
        "total_withdrawn": 0,
        "total_borrowed": 0,
        "total_repaid": 0,
        "interest_earned": 0,
        "interest_paid": 0,
        "transactions": [],
    }
    for key, value in bank_defaults.items():
        if isinstance(value, list):
            if not isinstance(bank.get(key), list):
                bank[key] = []
            else:
                bank.setdefault(key, [])
        else:
            bank.setdefault(key, value)
    bank["savings"] = max(0, int(bank.get("savings", 0) or 0))
    bank["loan_debt"] = max(0, int(bank.get("loan_debt", 0) or 0))
    bank["credit_score"] = max(0, min(1000, int(bank.get("credit_score", 500) or 500)))

    shark = finance.setdefault("loan_shark", {})
    if not isinstance(shark, dict):
        shark = {}
        finance["loan_shark"] = shark
    shark_defaults = {
        "debt": 0,
        "principal": 0,
        "last_interest_date": _kst_date(),
        "first_borrowed_at": "",
        "last_borrowed_at": "",
        "collection_level": 0,
        "total_borrowed": 0,
        "total_repaid": 0,
        "interest_paid": 0,
        "transactions": [],
    }
    for key, value in shark_defaults.items():
        if isinstance(value, list):
            if not isinstance(shark.get(key), list):
                shark[key] = []
            else:
                shark.setdefault(key, [])
        else:
            shark.setdefault(key, value)
    shark["debt"] = max(0, int(shark.get("debt", 0) or 0))
    shark["principal"] = max(0, int(shark.get("principal", 0) or 0))
    shark["collection_level"] = max(0, min(5, int(shark.get("collection_level", 0) or 0)))
    return finance


def _record_transaction(account: Dict[str, Any], action: str, amount: int, note: str, balance: int) -> None:
    history = account.setdefault("transactions", [])
    history.append(
        {
            "time": _utc_now().isoformat(),
            "action": action,
            "amount": int(amount),
            "note": note,
            "balance": int(balance),
        }
    )
    del history[:-FINANCE_HISTORY_LIMIT]


def _apply_interest(user: Dict[str, Any]) -> Dict[str, int]:
    finance = ensure_finance_profile(user)
    bank = finance["bank"]
    shark = finance["loan_shark"]
    result = {"days": 0, "savings_interest": 0, "bank_interest": 0, "shark_interest": 0}

    bank_days = _days_since(bank.get("last_interest_date"))
    if bank_days > 0:
        old_savings = int(bank.get("savings", 0))
        new_savings = _compound(old_savings, BANK_SAVINGS_DAILY_RATE, bank_days)
        earned = max(0, new_savings - old_savings)
        bank["savings"] = new_savings
        bank["interest_earned"] = int(bank.get("interest_earned", 0)) + earned

        old_debt = int(bank.get("loan_debt", 0))
        new_debt = _compound(old_debt, BANK_LOAN_DAILY_RATE, bank_days)
        debt_interest = max(0, new_debt - old_debt)
        bank["loan_debt"] = new_debt
        bank["interest_paid"] = int(bank.get("interest_paid", 0)) + debt_interest
        bank["last_interest_date"] = _kst_date()
        result["days"] = max(result["days"], bank_days)
        result["savings_interest"] = earned
        result["bank_interest"] = debt_interest

    shark_days = _days_since(shark.get("last_interest_date"))
    if shark_days > 0:
        old_debt = int(shark.get("debt", 0))
        new_debt = _compound(old_debt, LOAN_SHARK_DAILY_RATE, shark_days)
        shark_interest = max(0, new_debt - old_debt)
        shark["debt"] = new_debt
        shark["interest_paid"] = int(shark.get("interest_paid", 0)) + shark_interest
        shark["last_interest_date"] = _kst_date()
        if old_debt > 0:
            shark["collection_level"] = min(5, int(shark.get("collection_level", 0)) + shark_days // 3)
        result["days"] = max(result["days"], shark_days)
        result["shark_interest"] = shark_interest
    return result


def _bank_loan_limit(user: Dict[str, Any]) -> int:
    finance = ensure_finance_profile(user)
    bank = finance["bank"]
    level = max(1, int(user.get("level", 1) or 1))
    score = int(bank.get("credit_score", 500))
    savings = int(bank.get("savings", 0))
    limit = 100_000 + level * 50_000 + score * 2_000 + savings // 2
    return max(100_000, min(50_000_000, limit))


def _loan_shark_limit(user: Dict[str, Any]) -> int:
    level = max(1, int(user.get("level", 1) or 1))
    return min(30_000_000, 500_000 + level * 150_000)


def _valid_amount(amount: Any) -> Optional[int]:
    try:
        parsed = int(amount)
    except (TypeError, ValueError):
        return None
    if parsed < BANK_MIN_AMOUNT or parsed > BANK_MAX_TRANSACTION:
        return None
    return parsed


def _collection_label(level: int) -> str:
    labels = {
        0: "조용함",
        1: "독촉 메시지",
        2: "거친 경고",
        3: "추심원 배치",
        4: "거점 감시",
        5: "최고 위험",
    }
    return labels.get(max(0, min(5, int(level))), "알 수 없음")


def register_v40_finance_commands(
    bot: commands.Bot,
    get_user: Callable[[int], Dict[str, Any]],
    check_registered: Callable[..., Any],
    save_data: Callable[[], None],
) -> None:
    """V4.0 은행 예금·대출과 고위험 사채 시스템을 등록합니다."""

    async def require_user(ctx: commands.Context) -> Optional[Dict[str, Any]]:
        if not await check_registered(ctx):
            return None
        user = get_user(ctx.author.id)
        ensure_finance_profile(user)
        changed = _apply_interest(user)
        if any(int(v) > 0 for v in changed.values()):
            save_data()
        return user

    async def bank_status(ctx: commands.Context) -> None:
        user = await require_user(ctx)
        if user is None:
            return
        bank = ensure_finance_profile(user)["bank"]
        loan_limit = _bank_loan_limit(user)
        debt = int(bank.get("loan_debt", 0))
        available = max(0, loan_limit - debt)
        embed = discord.Embed(
            title="🏦 ABADDON 생존자 은행",
            description="안전한 예금과 심사형 대출을 제공합니다. 모든 수치는 게임 내 식량입니다.",
            color=discord.Color.blue(),
        )
        embed.add_field(name="💵 현금 식량", value=f"**{int(user.get('balance', 0)):,}개**", inline=True)
        embed.add_field(name="🏧 은행 예금", value=f"**{int(bank.get('savings', 0)):,}개**", inline=True)
        embed.add_field(name="📄 은행 대출금", value=f"**{debt:,}개**", inline=True)
        embed.add_field(name="💳 신용점수", value=f"**{int(bank.get('credit_score', 500))}/1000**", inline=True)
        embed.add_field(name="📈 대출 한도", value=f"총 {loan_limit:,} · 추가 {available:,}", inline=True)
        embed.add_field(name="🧾 일일 이율", value="예금 +0.3% · 대출 +2%", inline=True)
        embed.add_field(
            name="명령어",
            value=(
                "`/은행 입금 금액` · `/은행 출금 금액`\n"
                "`/은행 대출 금액` · `/은행 상환 금액`\n"
                "`/은행 이자` · `/은행 신용` · `/은행 기록`"
            ),
            inline=False,
        )
        embed.set_footer(text="식량 잔액은 룰렛 등으로 마이너스가 될 수 있음 · 예금은 마이너스 불가")
        await ctx.send(embed=embed)

    async def deposit(ctx: commands.Context, amount: int) -> None:
        user = await require_user(ctx)
        if user is None:
            return
        amount = _valid_amount(amount) or 0
        cash = int(user.get("balance", 0))
        if amount <= 0 or cash < amount:
            ctx.command.reset_cooldown(ctx)
            await ctx.send(f"⚠️ 입금 범위는 {BANK_MIN_AMOUNT:,}~{BANK_MAX_TRANSACTION:,}개이며 보유 식량은 **{cash:,}개**입니다.")
            return
        bank = ensure_finance_profile(user)["bank"]
        user["balance"] = cash - amount
        bank["savings"] = int(bank.get("savings", 0)) + amount
        bank["total_deposited"] = int(bank.get("total_deposited", 0)) + amount
        _record_transaction(bank, "입금", amount, "현금 식량을 예금", int(bank["savings"]))
        save_data()
        await ctx.send(f"🏦 **입금 완료**\n-{amount:,} 현금 · 예금 **{int(bank['savings']):,}개** · 현금 **{int(user['balance']):,}개**")

    async def withdraw(ctx: commands.Context, amount: int) -> None:
        user = await require_user(ctx)
        if user is None:
            return
        amount = _valid_amount(amount) or 0
        bank = ensure_finance_profile(user)["bank"]
        savings = int(bank.get("savings", 0))
        if amount <= 0 or savings < amount:
            ctx.command.reset_cooldown(ctx)
            await ctx.send(f"⚠️ 출금 가능 예금은 **{savings:,}개**입니다.")
            return
        bank["savings"] = savings - amount
        user["balance"] = int(user.get("balance", 0)) + amount
        bank["total_withdrawn"] = int(bank.get("total_withdrawn", 0)) + amount
        _record_transaction(bank, "출금", amount, "예금을 현금 식량으로 출금", int(bank["savings"]))
        save_data()
        await ctx.send(f"🏧 **출금 완료**\n+{amount:,} 현금 · 예금 **{int(bank['savings']):,}개** · 현금 **{int(user['balance']):,}개**")

    async def borrow_bank(ctx: commands.Context, amount: int) -> None:
        user = await require_user(ctx)
        if user is None:
            return
        amount = _valid_amount(amount) or 0
        bank = ensure_finance_profile(user)["bank"]
        limit = _bank_loan_limit(user)
        debt = int(bank.get("loan_debt", 0))
        available = max(0, limit - debt)
        if amount <= 0 or amount > available:
            ctx.command.reset_cooldown(ctx)
            await ctx.send(f"⚠️ 추가 대출 가능액은 **{available:,}개**입니다. 신용점수 **{int(bank.get('credit_score', 500))}**")
            return
        bank["loan_debt"] = debt + amount
        bank["total_borrowed"] = int(bank.get("total_borrowed", 0)) + amount
        bank["credit_score"] = max(0, int(bank.get("credit_score", 500)) - max(1, amount // 500_000))
        user["balance"] = int(user.get("balance", 0)) + amount
        _record_transaction(bank, "대출", amount, "은행 심사형 대출", int(bank["loan_debt"]))
        save_data()
        await ctx.send(
            f"📄 **은행 대출 승인**\n+{amount:,} 식량 · 현재 현금 **{int(user['balance']):,}개**\n"
            f"남은 은행 대출금 **{int(bank['loan_debt']):,}개** · 일일 이자 2%"
        )

    async def repay_bank(ctx: commands.Context, amount: int) -> None:
        user = await require_user(ctx)
        if user is None:
            return
        amount = _valid_amount(amount) or 0
        bank = ensure_finance_profile(user)["bank"]
        debt = int(bank.get("loan_debt", 0))
        cash = int(user.get("balance", 0))
        pay = min(amount, debt) if amount > 0 else 0
        if pay <= 0 or cash < pay:
            ctx.command.reset_cooldown(ctx)
            await ctx.send(f"⚠️ 상환할 은행 대출금 **{debt:,}개** · 보유 현금 **{cash:,}개**")
            return
        user["balance"] = cash - pay
        bank["loan_debt"] = debt - pay
        bank["total_repaid"] = int(bank.get("total_repaid", 0)) + pay
        bank["credit_score"] = min(1000, int(bank.get("credit_score", 500)) + max(1, pay // 100_000))
        _record_transaction(bank, "상환", pay, "은행 대출 상환", int(bank["loan_debt"]))
        save_data()
        await ctx.send(f"✅ **은행 대출 상환 완료**\n-{pay:,} 식량 · 남은 대출금 **{int(bank['loan_debt']):,}개** · 신용 **{int(bank['credit_score'])}**")

    async def interest_report(ctx: commands.Context) -> None:
        if not await check_registered(ctx):
            return
        user = get_user(ctx.author.id)
        ensure_finance_profile(user)
        result = _apply_interest(user)
        save_data()
        await ctx.send(
            "📈 **일일 이자 정산**\n"
            f"예금 이자 **+{int(result['savings_interest']):,}개**\n"
            f"은행 대출 이자 **+{int(result['bank_interest']):,}개**\n"
            f"사채 이자 **+{int(result['shark_interest']):,}개**\n"
            "같은 날에는 중복 정산되지 않습니다."
        )

    async def credit_report(ctx: commands.Context) -> None:
        user = await require_user(ctx)
        if user is None:
            return
        bank = ensure_finance_profile(user)["bank"]
        score = int(bank.get("credit_score", 500))
        if score >= 800:
            grade = "최우수"
        elif score >= 650:
            grade = "우수"
        elif score >= 450:
            grade = "보통"
        elif score >= 250:
            grade = "주의"
        else:
            grade = "위험"
        await ctx.send(
            f"💳 **생존자 신용 정보**\n점수 **{score}/1000 ({grade})**\n"
            f"은행 대출 한도 **{_bank_loan_limit(user):,}개**\n"
            "은행 대출 상환 시 상승하고 추가 대출 시 소폭 하락합니다. 사채는 은행 신용과 별도로 기록됩니다."
        )

    async def bank_history(ctx: commands.Context) -> None:
        user = await require_user(ctx)
        if user is None:
            return
        bank = ensure_finance_profile(user)["bank"]
        history = list(bank.get("transactions", []))[-10:]
        if not history:
            await ctx.send("📭 은행 거래 기록이 없습니다.")
            return
        lines = [
            f"• **{item.get('action')}** {_signed(int(item.get('amount', 0)))} · {item.get('note')} · 잔액 {int(item.get('balance', 0)):,}"
            for item in reversed(history)
        ]
        await ctx.send(embed=discord.Embed(title="🧾 최근 은행 거래", description="\n".join(lines), color=discord.Color.blue()))

    async def shark_status(ctx: commands.Context) -> None:
        user = await require_user(ctx)
        if user is None:
            return
        shark = ensure_finance_profile(user)["loan_shark"]
        debt = int(shark.get("debt", 0))
        limit = _loan_shark_limit(user)
        available = max(0, limit - int(shark.get("principal", 0)))
        level = int(shark.get("collection_level", 0))
        embed = discord.Embed(
            title="🕴️ 모르간 사금융",
            description=(
                "은행 심사 없이 즉시 식량을 빌릴 수 있지만 매우 위험합니다.\n"
                "빌리는 순간 10% 수수료가 원금에 붙고, 미상환액에는 매일 12% 복리 이자가 붙습니다."
            ),
            color=discord.Color.dark_red(),
        )
        embed.add_field(name="현재 사채 빚", value=f"**{debt:,}개**", inline=True)
        embed.add_field(name="추가 가능액", value=f"**{available:,}개**", inline=True)
        embed.add_field(name="추심 위험", value=f"**Lv.{level} · {_collection_label(level)}**", inline=True)
        embed.add_field(name="현금 식량", value=f"**{int(user.get('balance', 0)):,}개**", inline=True)
        embed.add_field(name="누적 차입", value=f"**{int(shark.get('total_borrowed', 0)):,}개**", inline=True)
        embed.add_field(name="누적 상환", value=f"**{int(shark.get('total_repaid', 0)):,}개**", inline=True)
        embed.add_field(
            name="명령어",
            value="`/사채 빌리기 금액` · `/사채 상환 금액` · `/사채 추심` · `/사채 기록`",
            inline=False,
        )
        embed.set_footer(text="게임 속 가상 사금융 · 실제 금융 서비스 아님 · 파산신청으로 사채 빚은 사라지지 않음")
        await ctx.send(embed=embed)

    async def borrow_shark(ctx: commands.Context, amount: int) -> None:
        user = await require_user(ctx)
        if user is None:
            return
        amount = _valid_amount(amount) or 0
        shark = ensure_finance_profile(user)["loan_shark"]
        limit = _loan_shark_limit(user)
        principal = int(shark.get("principal", 0))
        available = max(0, limit - principal)
        if amount <= 0 or amount > available:
            ctx.command.reset_cooldown(ctx)
            await ctx.send(f"⚠️ 추가로 빌릴 수 있는 사채 원금은 **{available:,}개**입니다.")
            return
        fee = int(math.ceil(amount * LOAN_SHARK_ORIGINATION_RATE))
        shark["principal"] = principal + amount
        shark["debt"] = int(shark.get("debt", 0)) + amount + fee
        shark["total_borrowed"] = int(shark.get("total_borrowed", 0)) + amount
        shark["last_borrowed_at"] = _utc_now().isoformat()
        shark["first_borrowed_at"] = shark.get("first_borrowed_at") or shark["last_borrowed_at"]
        shark["last_interest_date"] = _kst_date()
        user["balance"] = int(user.get("balance", 0)) + amount
        _record_transaction(shark, "차입", amount, f"개설 수수료 {fee:,}", int(shark["debt"]))
        save_data()
        await ctx.send(
            f"🕴️ **사채 계약 체결**\n실수령 **+{amount:,} 식량** · 개설 수수료 **{fee:,}**\n"
            f"즉시 발생한 빚 **{amount + fee:,}개** · 총 사채 빚 **{int(shark['debt']):,}개**\n"
            "⚠️ 매일 12% 복리 이자가 붙습니다."
        )

    async def repay_shark(ctx: commands.Context, amount: int) -> None:
        user = await require_user(ctx)
        if user is None:
            return
        amount = _valid_amount(amount) or 0
        shark = ensure_finance_profile(user)["loan_shark"]
        debt = int(shark.get("debt", 0))
        cash = int(user.get("balance", 0))
        pay = min(amount, debt) if amount > 0 else 0
        if pay <= 0 or cash < pay:
            ctx.command.reset_cooldown(ctx)
            await ctx.send(f"⚠️ 사채 빚 **{debt:,}개** · 보유 현금 **{cash:,}개**")
            return
        user["balance"] = cash - pay
        shark["debt"] = debt - pay
        shark["total_repaid"] = int(shark.get("total_repaid", 0)) + pay
        if int(shark["debt"]) <= 0:
            shark["debt"] = 0
            shark["principal"] = 0
            shark["collection_level"] = 0
            shark["first_borrowed_at"] = ""
        else:
            # 상환금은 누적 이자부터 갚고, 남는 금액만 실제 원금을 줄입니다.
            principal_before = int(shark.get("principal", 0))
            accrued_interest = max(0, debt - principal_before)
            principal_payment = max(0, pay - accrued_interest)
            shark["principal"] = max(0, principal_before - min(principal_before, principal_payment))
            shark["collection_level"] = max(0, int(shark.get("collection_level", 0)) - 1)
        _record_transaction(shark, "상환", pay, "사채 상환", int(shark["debt"]))
        save_data()
        await ctx.send(f"🧾 **사채 상환 완료**\n-{pay:,} 식량 · 남은 사채 빚 **{int(shark['debt']):,}개**")

    async def collection_event(ctx: commands.Context) -> None:
        user = await require_user(ctx)
        if user is None:
            return
        shark = ensure_finance_profile(user)["loan_shark"]
        debt = int(shark.get("debt", 0))
        if debt <= 0:
            await ctx.send("🕊️ 사채 빚이 없어 추심원이 찾아오지 않습니다.")
            return
        level = int(shark.get("collection_level", 0))
        messages = {
            0: "아직 연락은 없지만 이자는 계속 붙고 있습니다.",
            1: "낡은 무전기로 상환 독촉이 들어왔습니다.",
            2: "거점 입구에 붉은 경고장이 붙었습니다.",
            3: "검은 정장을 입은 추심원이 거점 주변을 돌고 있습니다.",
            4: "보급로가 감시받고 있습니다. 더 늦기 전에 상환해야 합니다.",
            5: "모르간이 직접 최종 경고를 보냈습니다. 빚이 폭증하고 있습니다.",
        }
        penalty = 0
        if level >= 3:
            finance = ensure_finance_profile(user)
            bank = finance["bank"]
            penalty = min(30, level * 5)
            bank["credit_score"] = max(0, int(bank.get("credit_score", 500)) - penalty)
            save_data()
        await ctx.send(
            f"🚨 **사채 추심 위험 Lv.{level}**\n{messages.get(level, messages[5])}\n"
            f"현재 빚 **{debt:,}개**" + (f"\n은행 신용 **-{penalty}점**" if penalty else "")
        )

    async def shark_history(ctx: commands.Context) -> None:
        user = await require_user(ctx)
        if user is None:
            return
        shark = ensure_finance_profile(user)["loan_shark"]
        history = list(shark.get("transactions", []))[-10:]
        if not history:
            await ctx.send("📭 사채 거래 기록이 없습니다.")
            return
        lines = [
            f"• **{item.get('action')}** {_signed(int(item.get('amount', 0)))} · {item.get('note')} · 빚 {int(item.get('balance', 0)):,}"
            for item in reversed(history)
        ]
        await ctx.send(embed=discord.Embed(title="🩸 최근 사채 기록", description="\n".join(lines), color=discord.Color.dark_red()))

    # 은행 slash 그룹
    @bot.hybrid_group(
        name="은행",
        fallback="현황",
        invoke_without_command=True,
        description="예금, 출금, 은행 대출과 신용을 관리합니다.",
    )
    async def bank_group(ctx: commands.Context) -> None:
        await bank_status(ctx)

    @bank_group.command(name="입금", description="현금 식량을 은행 예금으로 이동합니다.")
    async def bank_deposit_cmd(ctx: commands.Context, 금액: int) -> None:
        await deposit(ctx, 금액)

    @bank_group.command(name="출금", description="은행 예금을 현금 식량으로 출금합니다.")
    async def bank_withdraw_cmd(ctx: commands.Context, 금액: int) -> None:
        await withdraw(ctx, 금액)

    @bank_group.command(name="대출", description="신용 한도 안에서 은행 대출을 받습니다.")
    async def bank_borrow_cmd(ctx: commands.Context, 금액: int) -> None:
        await borrow_bank(ctx, 금액)

    @bank_group.command(name="상환", description="은행 대출금을 상환합니다.")
    async def bank_repay_cmd(ctx: commands.Context, 금액: int) -> None:
        await repay_bank(ctx, 금액)

    @bank_group.command(name="이자", description="오늘까지의 예금·대출·사채 이자를 정산합니다.")
    async def bank_interest_cmd(ctx: commands.Context) -> None:
        await interest_report(ctx)

    @bank_group.command(name="신용", description="신용점수와 은행 대출 한도를 확인합니다.")
    async def bank_credit_cmd(ctx: commands.Context) -> None:
        await credit_report(ctx)

    @bank_group.command(name="기록", description="최근 은행 거래 기록을 확인합니다.")
    async def bank_history_cmd(ctx: commands.Context) -> None:
        await bank_history(ctx)

    # 사채 slash 그룹
    @bot.hybrid_group(
        name="사채",
        fallback="현황",
        invoke_without_command=True,
        description="고금리 사금융 차입, 상환과 추심 위험을 관리합니다.",
    )
    async def shark_group(ctx: commands.Context) -> None:
        await shark_status(ctx)

    @shark_group.command(name="빌리기", description="은행 심사 없이 고금리 사채를 빌립니다.")
    async def shark_borrow_cmd(ctx: commands.Context, 금액: int) -> None:
        await borrow_shark(ctx, 금액)

    @shark_group.command(name="상환", description="사채 빚을 상환합니다.")
    async def shark_repay_cmd(ctx: commands.Context, 금액: int) -> None:
        await repay_shark(ctx, 금액)

    @shark_group.command(name="추심", description="현재 사채 추심 위험과 경고를 확인합니다.")
    async def shark_collection_cmd(ctx: commands.Context) -> None:
        await collection_event(ctx)

    @shark_group.command(name="기록", description="최근 사채 차입과 상환 기록을 확인합니다.")
    async def shark_history_cmd(ctx: commands.Context) -> None:
        await shark_history(ctx)

    # prefix 바로가기
    @bot.command(name="입금")
    async def bank_deposit_prefix(ctx: commands.Context, 금액: int) -> None:
        await deposit(ctx, 금액)

    @bot.command(name="출금")
    async def bank_withdraw_prefix(ctx: commands.Context, 금액: int) -> None:
        await withdraw(ctx, 금액)

    @bot.command(name="대출")
    async def bank_borrow_prefix(ctx: commands.Context, 금액: int) -> None:
        await borrow_bank(ctx, 금액)

    @bot.command(name="상환")
    async def bank_repay_prefix(ctx: commands.Context, 금액: int) -> None:
        await repay_bank(ctx, 금액)

    @bot.command(name="은행이자")
    async def bank_interest_prefix(ctx: commands.Context) -> None:
        await interest_report(ctx)

    @bot.command(name="신용")
    async def bank_credit_prefix(ctx: commands.Context) -> None:
        await credit_report(ctx)

    @bot.command(name="은행기록")
    async def bank_history_prefix(ctx: commands.Context) -> None:
        await bank_history(ctx)

    @bot.command(name="사채빌리기")
    async def shark_borrow_prefix(ctx: commands.Context, 금액: int) -> None:
        await borrow_shark(ctx, 금액)

    @bot.command(name="사채상환")
    async def shark_repay_prefix(ctx: commands.Context, 금액: int) -> None:
        await repay_shark(ctx, 금액)

    @bot.command(name="사채추심")
    async def shark_collection_prefix(ctx: commands.Context) -> None:
        await collection_event(ctx)

    @bot.command(name="사채기록")
    async def shark_history_prefix(ctx: commands.Context) -> None:
        await shark_history(ctx)
