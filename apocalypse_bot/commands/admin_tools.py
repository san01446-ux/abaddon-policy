import discord
from discord.ext import commands

from apocalypse_bot.commands.status import get_max_hp, get_max_stamina
from apocalypse_bot.commands.conditions import ensure_conditions
from apocalypse_bot.commands.world_exploration import REGIONS
from apocalypse_bot.game_data.jobs import JOBS

MEDICAL_ITEMS = ("붕대", "소독약", "항생제", "진통제", "백신")
BASIC_RESOURCES = ("나무", "광석", "물고기", "약초", "고철")


def register_admin_commands(
    bot,
    get_user,
    save_data,
    send_pages,
    item_db,
    materials,
    pet_db,
    calculate_user_power,
):
    def is_admin(ctx):
        return bool(ctx.guild and ctx.author.guild_permissions.administrator)

    async def require_admin(ctx):
        if not is_admin(ctx):
            await ctx.send("❌ 이 명령어는 **서버 관리자**만 사용할 수 있습니다.")
            return False
        return True

    async def target_user(ctx, member):
        user = get_user(member.id)
        if not user:
            await ctx.send("⚠️ 해당 유저는 아직 가입하지 않았습니다.")
            return None
        return user

    def equipment_names():
        return {name for items in item_db.values() for name in items}

    def category_of(name):
        if name in equipment_names():
            return "장비"
        if name in MEDICAL_ITEMS:
            return "의약품"
        if name in materials:
            return "제작재료"
        if name in BASIC_RESOURCES:
            return "생활자원"
        return None

    def add_named_item(user, name, amount):
        category = category_of(name)
        if category == "장비":
            user.setdefault("inventory", []).extend([name] * amount)
        elif category == "의약품":
            user.setdefault("medical_items", {})
            user["medical_items"][name] = user["medical_items"].get(name, 0) + amount
        elif category == "제작재료":
            user.setdefault("materials", {})
            user["materials"][name] = user["materials"].get(name, 0) + amount
        elif category == "생활자원":
            user.setdefault("resources", {})
            user["resources"][name] = user["resources"].get(name, 0) + amount
        return category

    def remove_named_item(user, name, amount):
        category = category_of(name)
        if category == "장비":
            inventory = user.setdefault("inventory", [])
            owned = inventory.count(name)
            removed = min(owned, amount)
            for _ in range(removed):
                inventory.remove(name)
            # 장착 중인데 가방에도 같은 이름이 하나도 남지 않으면 자동 해제
            if name not in inventory:
                for slot, equipped in user.setdefault("equipment", {}).items():
                    if equipped == name:
                        user["equipment"][slot] = None
            return category, removed
        store_key = {
            "의약품": "medical_items",
            "제작재료": "materials",
            "생활자원": "resources",
        }.get(category)
        if not store_key:
            return None, 0
        store = user.setdefault(store_key, {})
        removed = min(max(0, int(store.get(name, 0))), amount)
        store[name] = max(0, int(store.get(name, 0)) - removed)
        return category, removed

    @bot.command(name="관리자명령어")
    async def admin_help(ctx):
        if not await require_admin(ctx):
            return
        text = (
            "👑 **[관리자 도구 V2.0-6]**\n\n"
            "**통합 지급/회수**\n"
            "`!아이템지급 @유저 이름 수량` / `!아이템회수 @유저 이름 수량`\n"
            "`!아이템목록` / `!아이템검색 검색어`\n\n"
            "**재화·성장**\n"
            "`!식량지급 @유저 수량` / `!식량회수 @유저 수량`\n"
            "`!경험치지급 @유저 수량` / `!레벨설정 @유저 레벨`\n"
            "`!직업설정 @유저 직업명` / `!펫설정 @유저 펫이름`\n"
            "`!칭호지급 @유저 칭호`\n\n"
            "**생존 상태**\n"
            "`!체력설정 @유저 수치` / `!스태미나설정 @유저 수치`\n"
            "`!감염도설정 @유저 0~100` / `!상태이상제거 @유저`\n"
            "`!관리자지역이동 @유저 지역명` / `!유저정보 @유저`\n\n"
            "**서버 자동 꾸미기**\n"
            "`!서버세팅 미리보기` / `!서버세팅 실행` / `!서버세팅 상태` / `!서버세팅 취소`\n\n"
            "💡 `!아이템지급`은 장비·의약품·제작재료·생활자원을 자동 구분합니다."
        )
        await ctx.send(text)

    @bot.command(name="아이템목록")
    async def item_list(ctx):
        if not await require_admin(ctx):
            return
        lines = ["📦 **[관리자 지급 가능 목록]**"]
        for tier, items in item_db.items():
            lines.append(f"\n⚔️ **{tier} 장비 ({len(items)}종)**")
            lines.append(", ".join(items.keys()))
        lines.append("\n💊 **의약품**\n" + ", ".join(MEDICAL_ITEMS))
        lines.append("\n🧰 **제작재료**\n" + ", ".join(materials))
        lines.append("\n🌲 **생활자원**\n" + ", ".join(BASIC_RESOURCES))
        lines.append("\n🐾 **펫**\n" + ", ".join(pet_db.keys()))
        lines.append("\n👔 **직업**\n" + ", ".join(JOBS.keys()))
        lines.append("\n🗺️ **지역**\n" + ", ".join(REGIONS.keys()))
        await send_pages(ctx.channel, "\n".join(lines))

    @bot.command(name="아이템검색")
    async def item_search(ctx, *, 검색어: str = ""):
        if not await require_admin(ctx):
            return
        query = 검색어.strip().lower()
        if not query:
            await ctx.send("⚠️ 사용법: `!아이템검색 방탄`")
            return
        pools = {
            "장비": sorted(equipment_names()),
            "의약품": list(MEDICAL_ITEMS),
            "제작재료": list(materials),
            "생활자원": list(BASIC_RESOURCES),
            "펫": list(pet_db.keys()),
            "직업": list(JOBS.keys()),
            "지역": list(REGIONS.keys()),
        }
        found = []
        for category, names in pools.items():
            matches = [name for name in names if query in name.lower()]
            if matches:
                found.append(f"**{category}**: " + ", ".join(matches))
        if not found:
            await ctx.send(f"🔎 **'{검색어}'** 검색 결과가 없습니다.")
            return
        await send_pages(ctx.channel, "🔎 **[검색 결과]**\n" + "\n".join(found))

    @bot.command(name="아이템지급")
    async def give_item(ctx, 대상: discord.Member, 아이템이름: str, 수량: int = 1):
        if not await require_admin(ctx):
            return
        user = await target_user(ctx, 대상)
        if not user:
            return
        if 수량 <= 0 or 수량 > 100000:
            await ctx.send("⚠️ 수량은 **1~100,000** 사이로 입력하세요.")
            return
        category = add_named_item(user, 아이템이름, 수량)
        if not category:
            await ctx.send("⚠️ 존재하지 않는 이름입니다. `!아이템검색 검색어`로 확인하세요.")
            return
        save_data()
        await ctx.send(f"✅ {대상.mention}에게 **[{category}] {아이템이름} × {수량:,}** 지급했습니다.")

    @bot.command(name="아이템회수")
    async def take_item(ctx, 대상: discord.Member, 아이템이름: str, 수량: int = 1):
        if not await require_admin(ctx):
            return
        user = await target_user(ctx, 대상)
        if not user:
            return
        if 수량 <= 0:
            await ctx.send("⚠️ 수량은 1 이상이어야 합니다.")
            return
        category, removed = remove_named_item(user, 아이템이름, 수량)
        if not category:
            await ctx.send("⚠️ 존재하지 않는 이름입니다. `!아이템검색 검색어`로 확인하세요.")
            return
        if removed <= 0:
            await ctx.send(f"⚠️ {대상.mention}은(는) **{아이템이름}**을 보유하지 않았습니다.")
            return
        save_data()
        await ctx.send(f"✅ {대상.mention}에게서 **[{category}] {아이템이름} × {removed:,}** 회수했습니다.")

    @bot.command(name="경험치지급")
    async def give_exp(ctx, 대상: discord.Member, 수량: int):
        if not await require_admin(ctx): return
        user = await target_user(ctx, 대상)
        if not user: return
        if 수량 <= 0:
            await ctx.send("⚠️ 경험치는 1 이상 입력하세요.")
            return
        user["exp"] = max(0, int(user.get("exp", 0)) + 수량)
        save_data()
        await ctx.send(f"✅ {대상.mention}에게 경험치 **{수량:,}** 지급. 현재 **{user['exp']:,} EXP**")

    @bot.command(name="레벨설정")
    async def set_level(ctx, 대상: discord.Member, 레벨: int):
        if not await require_admin(ctx): return
        user = await target_user(ctx, 대상)
        if not user: return
        if not 1 <= 레벨 <= 10000:
            await ctx.send("⚠️ 레벨은 **1~10,000** 사이로 설정하세요.")
            return
        user["level"] = 레벨
        user["hp"] = min(int(user.get("hp", 0)), get_max_hp(user))
        user["stamina"] = min(int(user.get("stamina", 0)), get_max_stamina(user))
        save_data()
        await ctx.send(f"✅ {대상.mention}의 레벨을 **Lv.{레벨}**로 설정했습니다.")

    @bot.command(name="직업설정")
    async def set_job(ctx, 대상: discord.Member, *, 직업명: str):
        if not await require_admin(ctx): return
        user = await target_user(ctx, 대상)
        if not user: return
        name = 직업명.strip()
        if name not in JOBS:
            await ctx.send("⚠️ 존재하지 않는 직업입니다: " + ", ".join(JOBS.keys()))
            return
        user["job"] = name
        save_data()
        await ctx.send(f"✅ {대상.mention}의 직업을 **{name}**(으)로 설정했습니다.")

    @bot.command(name="펫설정")
    async def set_pet(ctx, 대상: discord.Member, *, 펫이름: str):
        if not await require_admin(ctx): return
        user = await target_user(ctx, 대상)
        if not user: return
        name = 펫이름.strip()
        if name in ("없음", "해제", "제거"):
            user["pet"] = None
            user["pet_level"] = 1
            save_data()
            await ctx.send(f"✅ {대상.mention}의 펫을 해제했습니다.")
            return
        if name not in pet_db:
            await ctx.send("⚠️ 존재하지 않는 펫입니다: " + ", ".join(pet_db.keys()))
            return
        collection = user.setdefault("pet_collection", {})
        record = collection.setdefault(name, {
            "level": 1, "exp": 0, "friendship": 0, "evolution": 0,
            "last_feed": "", "last_adventure": "",
        })
        if not isinstance(record, dict):
            record = {
                "level": 1, "exp": 0, "friendship": 0, "evolution": 0,
                "last_feed": "", "last_adventure": "",
            }
            collection[name] = record
        record.setdefault("level", max(1, int(user.get("pet_level", 1) or 1)))
        record.setdefault("exp", 0)
        record.setdefault("friendship", 0)
        record.setdefault("evolution", 0)
        record.setdefault("last_feed", "")
        record.setdefault("last_adventure", "")
        user["pet"] = name
        user["pet_level"] = max(1, int(record.get("level", 1) or 1))
        codex = user.setdefault("collection_codex", {}).setdefault("pets", [])
        if name not in codex:
            codex.append(name)
        save_data()
        await ctx.send(f"✅ {대상.mention}에게 펫 **{name}**을 지급하고 장착했습니다.")

    @bot.command(name="칭호지급")
    async def give_title(ctx, 대상: discord.Member, *, 칭호: str):
        if not await require_admin(ctx): return
        user = await target_user(ctx, 대상)
        if not user: return
        title = 칭호.strip()
        if not title:
            await ctx.send("⚠️ 칭호를 입력하세요.")
            return
        user.setdefault("titles", [])
        if title not in user["titles"]:
            user["titles"].append(title)
        save_data()
        await ctx.send(f"✅ {대상.mention}에게 칭호 **{title}** 지급했습니다.")

    @bot.command(name="체력설정")
    async def set_hp(ctx, 대상: discord.Member, 수치: int):
        if not await require_admin(ctx): return
        user = await target_user(ctx, 대상)
        if not user: return
        maximum = get_max_hp(user)
        user["hp"] = max(0, min(수치, maximum))
        save_data()
        await ctx.send(f"✅ {대상.mention}의 HP를 **{user['hp']} / {maximum}**으로 설정했습니다.")

    @bot.command(name="스태미나설정")
    async def set_stamina(ctx, 대상: discord.Member, 수치: int):
        if not await require_admin(ctx): return
        user = await target_user(ctx, 대상)
        if not user: return
        maximum = get_max_stamina(user)
        user["stamina"] = max(0, min(수치, maximum))
        save_data()
        await ctx.send(f"✅ {대상.mention}의 스태미나를 **{user['stamina']} / {maximum}**으로 설정했습니다.")

    @bot.command(name="감염도설정")
    async def set_infection(ctx, 대상: discord.Member, 수치: int):
        if not await require_admin(ctx): return
        user = await target_user(ctx, 대상)
        if not user: return
        if not 0 <= 수치 <= 100:
            await ctx.send("⚠️ 감염도는 **0~100** 사이로 입력하세요.")
            return
        user["infection"] = 수치
        ensure_conditions(user)
        user["conditions"]["감염"] = max(0, min(5, (수치 + 19) // 20)) if 수치 else 0
        save_data()
        await ctx.send(f"✅ {대상.mention}의 감염도를 **{수치}%**로 설정했습니다.")

    @bot.command(name="상태이상제거")
    async def clear_conditions(ctx, 대상: discord.Member):
        if not await require_admin(ctx): return
        user = await target_user(ctx, 대상)
        if not user: return
        ensure_conditions(user)
        for name in user["conditions"]:
            user["conditions"][name] = 0
        user["infection"] = 0
        save_data()
        await ctx.send(f"✅ {대상.mention}의 모든 상태 이상과 감염도를 제거했습니다.")

    @bot.command(name="관리자지역이동")
    async def admin_move(ctx, 대상: discord.Member, *, 지역명: str):
        if not await require_admin(ctx): return
        user = await target_user(ctx, 대상)
        if not user: return
        name = 지역명.strip()
        if name not in REGIONS:
            await ctx.send("⚠️ 존재하지 않는 지역입니다: " + ", ".join(REGIONS.keys()))
            return
        user["region"] = name
        user.setdefault("region_discoveries", [])
        if name not in user["region_discoveries"]:
            user["region_discoveries"].append(name)
        save_data()
        await ctx.send(f"✅ {대상.mention}을(를) **{name}** 지역으로 이동했습니다.")

    @bot.command(name="유저정보")
    async def user_info(ctx, 대상: discord.Member):
        if not await require_admin(ctx): return
        user = await target_user(ctx, 대상)
        if not user: return
        equipped = ", ".join(x for x in user.get("equipment", {}).values() if x) or "없음"
        conditions = ", ".join(f"{k} {v}" for k, v in user.get("conditions", {}).items() if v) or "정상"
        await ctx.send(
            f"👑 **[관리자 조회: {대상.name}]**\n"
            f"레벨 **{user.get('level', 1)}** | EXP **{user.get('exp', 0):,}** | 직업 **{user.get('job') or '없음'}**\n"
            f"식량 **{user.get('balance', 0):,}개** | 전투력 **{calculate_user_power(user):,}**\n"
            f"HP **{user.get('hp', 0)}/{get_max_hp(user)}** | 스태미나 **{user.get('stamina', 0)}/{get_max_stamina(user)}**\n"
            f"감염도 **{user.get('infection', 0)}%** | 상태 **{conditions}**\n"
            f"지역 **{user.get('region', '폐허도심')}** | 펫 **{user.get('pet') or '없음'}**\n"
            f"장착 장비: {equipped}\n"
            f"가방 장비 수: **{len(user.get('inventory', []))}개**"
        )
