import hashlib
import re
from datetime import datetime
from copy import deepcopy
from zoneinfo import ZoneInfo

from apocalypse_bot.commands.quiz_bank_v1802 import EXTRA_QUESTIONS


BASE_QUESTIONS = [
    {"category":"일반상식","q":"대한민국의 수도는 어디일까요?","choices":["부산","서울","대전","광주"],"answer":"2","aliases":["서울"]},
    {"category":"일반상식","q":"지구의 위성은 무엇일까요?","choices":["태양","화성","달","금성"],"answer":"3","aliases":["달"]},
    {"category":"일반상식","q":"1년은 보통 며칠일까요?","choices":["360일","365일","370일","400일"],"answer":"2","aliases":["365","365일"]},
    {"category":"일반상식","q":"무지개의 전통적인 색 개수는 몇 개일까요?","choices":["5개","6개","7개","8개"],"answer":"3","aliases":["7","7개"]},
    {"category":"일반상식","q":"올림픽 오륜기의 고리 개수는 몇 개일까요?","choices":["4개","5개","6개","7개"],"answer":"2","aliases":["5","5개"]},
    {"category":"한국사","q":"훈민정음을 창제한 왕은 누구일까요?","choices":["태조","세종대왕","정조","고종"],"answer":"2","aliases":["세종","세종대왕"]},
    {"category":"한국사","q":"고구려·백제·신라를 묶어 부르는 말은?","choices":["삼국","오대","남북국","후삼국"],"answer":"1","aliases":["삼국"]},
    {"category":"한국사","q":"임진왜란 당시 조선 수군을 이끈 장군은?","choices":["강감찬","을지문덕","이순신","김유신"],"answer":"3","aliases":["이순신"]},
    {"category":"한국사","q":"대한민국의 국기는 무엇일까요?","choices":["태극기","성조기","오성홍기","일장기"],"answer":"1","aliases":["태극기"]},
    {"category":"한국사","q":"한글날은 몇 월 며칠일까요?","choices":["8월 15일","10월 3일","10월 9일","12월 25일"],"answer":"3","aliases":["10월9일","10월 9일"]},
    {"category":"세계사","q":"고대 이집트 문명과 가장 관련 깊은 강은?","choices":["나일강","한강","아마존강","템스강"],"answer":"1","aliases":["나일강","나일"]},
    {"category":"세계사","q":"르네상스가 먼저 크게 발전한 지역은?","choices":["이탈리아","호주","남극","캐나다"],"answer":"1","aliases":["이탈리아"]},
    {"category":"세계사","q":"만리장성이 있는 나라는?","choices":["한국","중국","일본","몽골"],"answer":"2","aliases":["중국"]},
    {"category":"과학","q":"물의 화학식은 무엇일까요?","choices":["CO2","O2","H2O","NaCl"],"answer":"3","aliases":["h2o","H2O"]},
    {"category":"과학","q":"식물이 빛을 이용해 양분을 만드는 과정은?","choices":["증발","광합성","응결","연소"],"answer":"2","aliases":["광합성"]},
    {"category":"과학","q":"사람이 숨을 쉴 때 주로 필요한 기체는?","choices":["산소","헬륨","수소","네온"],"answer":"1","aliases":["산소"]},
    {"category":"과학","q":"태양계에서 가장 큰 행성은?","choices":["지구","화성","목성","수성"],"answer":"3","aliases":["목성"]},
    {"category":"과학","q":"물은 표준 대기압에서 몇 도에 얼까요?","choices":["0도","10도","50도","100도"],"answer":"1","aliases":["0","0도"]},
    {"category":"과학","q":"소리의 세기를 나타내는 단위로 흔히 쓰이는 것은?","choices":["미터","데시벨","리터","볼트"],"answer":"2","aliases":["데시벨","db"]},
    {"category":"IT","q":"컴퓨터의 중앙처리장치를 뜻하는 약자는?","choices":["CPU","USB","PDF","GPS"],"answer":"1","aliases":["cpu"]},
    {"category":"IT","q":"웹페이지의 구조를 작성하는 대표적인 언어는?","choices":["HTML","MP3","PNG","ZIP"],"answer":"1","aliases":["html"]},
    {"category":"IT","q":"이메일 주소에서 흔히 사용하는 기호는?","choices":["#","@","%","&"],"answer":"2","aliases":["@","골뱅이"]},
    {"category":"IT","q":"파일을 묶고 용량을 줄이는 형식으로 널리 쓰이는 것은?","choices":["ZIP","JPG","WAV","TXT"],"answer":"1","aliases":["zip"]},
    {"category":"군사","q":"부대 위치와 이동 경로를 확인할 때 가장 기본적으로 쓰는 것은?","choices":["지도","체온계","계산기","확성기"],"answer":"1","aliases":["지도"]},
    {"category":"군사","q":"위험지역에서 서로의 위치와 상황을 공유하는 행위를 가장 가깝게 부르는 말은?","choices":["상황전파","취침","정비","급식"],"answer":"1","aliases":["상황전파","보고"]},
    {"category":"생존","q":"출혈이 발생했을 때 가장 먼저 고려할 처치는?","choices":["압박 지혈","달리기","뜨거운 물 붓기","방치"],"answer":"1","aliases":["압박지혈","압박 지혈","지혈"]},
    {"category":"생존","q":"길을 잃었을 때 체력 소모를 줄이기 위한 좋은 행동은?","choices":["무작정 전력질주","안전한 곳에서 위치 파악","소리 없이 계속 이동","물 전부 버리기"],"answer":"2","aliases":["위치 파악","2"]},
    {"category":"생존","q":"오염이 의심되는 물은 어떻게 하는 것이 안전할까요?","choices":["그대로 마신다","가능하면 정수·끓이기","색만 보고 마신다","냄새만 맡고 마신다"],"answer":"2","aliases":["끓이기","정수","정수 끓이기"]},
    {"category":"생존","q":"비상식량을 관리하는 가장 좋은 방법은?","choices":["유통기한과 수량을 기록한다","한 번에 전부 먹는다","습한 곳에 둔다","포장을 모두 뜯는다"],"answer":"1","aliases":["기록","유통기한 기록"]},
    {"category":"좀비","q":"좀비가 많은 지역을 이동할 때 가장 중요한 원칙은?","choices":["소음을 크게 낸다","퇴로와 주변을 확인한다","혼자 돌진한다","불빛을 계속 흔든다"],"answer":"2","aliases":["퇴로 확인","주변 확인"]},
    {"category":"좀비","q":"감염 의심 상처가 생겼을 때 가장 적절한 행동은?","choices":["숨긴다","즉시 알리고 격리·처치한다","흙을 바른다","계속 전투한다"],"answer":"2","aliases":["격리","알리고 처치"]},
    {"category":"게임","q":"RPG에서 HP는 보통 무엇을 뜻할까요?","choices":["체력","화폐","속도","경험치"],"answer":"1","aliases":["체력","생명력"]},
    {"category":"게임","q":"RPG에서 EXP는 보통 무엇을 뜻할까요?","choices":["방어력","경험치","아이템 수","이동속도"],"answer":"2","aliases":["경험치"]},
    {"category":"게임","q":"보스 처치 후 얻는 보상을 흔히 무엇이라 할까요?","choices":["드롭","로그아웃","핑","프레임"],"answer":"1","aliases":["드롭","보상"]},
    {"category":"언어","q":"영어 알파벳은 모두 몇 글자일까요?","choices":["24","25","26","27"],"answer":"3","aliases":["26","26개"]},
    {"category":"언어","q":"'apple'의 한국어 뜻은?","choices":["사과","바나나","포도","복숭아"],"answer":"1","aliases":["사과"]},
    {"category":"언어","q":"'water'의 한국어 뜻은?","choices":["불","바람","물","땅"],"answer":"3","aliases":["물"]},
    {"category":"지리","q":"대한민국에서 가장 큰 섬은?","choices":["제주도","울릉도","강화도","거제도"],"answer":"1","aliases":["제주도","제주"]},
    {"category":"지리","q":"세계에서 가장 넓은 대양은?","choices":["태평양","대서양","인도양","북극해"],"answer":"1","aliases":["태평양"]},
    {"category":"지리","q":"프랑스의 수도는?","choices":["런던","파리","로마","마드리드"],"answer":"2","aliases":["파리"]},
    {"category":"지리","q":"일본의 수도는?","choices":["오사카","교토","도쿄","삿포로"],"answer":"3","aliases":["도쿄"]},
    {"category":"스포츠","q":"축구에서 한 팀이 경기장에 내보내는 선수는 보통 몇 명일까요?","choices":["9명","10명","11명","12명"],"answer":"3","aliases":["11","11명"]},
    {"category":"스포츠","q":"야구에서 스트라이크가 몇 번이면 타자가 아웃될까요?","choices":["2번","3번","4번","5번"],"answer":"2","aliases":["3","3번"]},
    {"category":"넌센스","q":"세상에서 가장 뜨거운 과일은?","choices":["천도복숭아","사과","포도","배"],"answer":"1","aliases":["천도복숭아"]},
    {"category":"넌센스","q":"왕이 넘어지면?","choices":["킹콩","왕복","킹덤","왕관"],"answer":"1","aliases":["킹콩"]},
    {"category":"넌센스","q":"오리가 얼면?","choices":["언덕","얼음오리","동상","오리탕"],"answer":"1","aliases":["언덕"]},
    {"category":"생존","q":"저체온증이 의심될 때 가장 적절한 행동은?","choices":["젖은 옷을 그대로 둔다","마른 옷과 담요로 천천히 보온한다","찬물을 마신다","강하게 달리게 한다"],"answer":"2","aliases":["보온","천천히 보온"]},
    {"category":"생존","q":"화재 시 연기가 가득한 통로를 이동해야 한다면?","choices":["몸을 낮추고 이동한다","서서 빠르게 뛴다","엘리베이터를 탄다","문을 모두 연다"],"answer":"1","aliases":["몸을 낮춘다","낮게 이동"]},
    {"category":"생존","q":"식량을 장기간 보관할 때 가장 피해야 할 환경은?","choices":["서늘하고 건조한 곳","직사광선과 습기가 많은 곳","밀봉된 용기","유통기한 표시"],"answer":"2","aliases":["습기","직사광선"]},
    {"category":"좀비","q":"폐건물 진입 전 가장 먼저 확인할 것은?","choices":["탈출 경로와 구조 안정성","전리품 가격","낙서 내용","창문 색깔"],"answer":"1","aliases":["탈출 경로","구조 안정성"]},
    {"category":"좀비","q":"감염자 무리를 피할 때 유리한 이동 방식은?","choices":["소음을 최소화하고 시야가 확보된 길을 택한다","경적을 울린다","좁은 막다른 골목으로 간다","불을 크게 피운다"],"answer":"1","aliases":["소음 최소화","시야 확보"]},
    {"category":"군사","q":"경계 근무에서 사각지대를 줄이는 기본 방법은?","choices":["관측 구역을 겹치게 배치한다","한 방향만 본다","조명을 모두 끈다","보고를 생략한다"],"answer":"1","aliases":["관측 구역 중첩","겹치게 배치"]},
    {"category":"군사","q":"무전 통신에서 메시지를 짧고 명확하게 전달하는 주된 이유는?","choices":["통신 시간을 줄이고 오해를 막기 위해","목소리를 크게 내기 위해","배터리를 빨리 쓰기 위해","암호를 없애기 위해"],"answer":"1","aliases":["오해 방지","통신 시간 단축"]},
    {"category":"IT","q":"인터넷에서 데이터를 작은 단위로 나누어 전송할 때 그 단위를 흔히 무엇이라 할까요?","choices":["패킷","픽셀","프레임","셀"],"answer":"1","aliases":["패킷"]},
    {"category":"IT","q":"비밀번호 보안을 강화하는 가장 좋은 방법은?","choices":["사이트마다 길고 다른 비밀번호를 사용한다","생일만 사용한다","모든 사이트에 같은 비밀번호를 쓴다","비밀번호를 공개 메모에 적는다"],"answer":"1","aliases":["다른 비밀번호","길고 다른 비밀번호"]},
    {"category":"과학","q":"대기 중 가장 많은 비율을 차지하는 기체는?","choices":["산소","질소","이산화탄소","수소"],"answer":"2","aliases":["질소"]},
    {"category":"과학","q":"전류의 세기를 나타내는 단위는?","choices":["볼트","암페어","와트","옴"],"answer":"2","aliases":["암페어","a"]},
    {"category":"한국사","q":"고려를 건국한 인물은?","choices":["왕건","이성계","궁예","견훤"],"answer":"1","aliases":["왕건","태조 왕건"]},
    {"category":"한국사","q":"조선 후기 수원 화성을 축조한 왕은?","choices":["세종","정조","숙종","철종"],"answer":"2","aliases":["정조"]},
    {"category":"세계사","q":"산업혁명이 가장 먼저 본격적으로 시작된 나라는?","choices":["영국","프랑스","미국","독일"],"answer":"1","aliases":["영국"]},
    {"category":"지리","q":"적도가 지나는 대륙이 아닌 것은?","choices":["아프리카","남아메리카","아시아","유럽"],"answer":"4","aliases":["유럽"]},
    {"category":"게임","q":"협동 레이드에서 탱커 역할의 핵심은?","choices":["적의 공격을 받아내고 아군을 보호한다","회복만 담당한다","아이템만 줍는다","전투에서 빠진다"],"answer":"1","aliases":["아군 보호","공격을 받아낸다"]},
    {"category":"게임","q":"치명타 확률이 20%라는 뜻에 가장 가까운 것은?","choices":["평균적으로 공격 5회 중 약 1회 치명타","모든 공격이 20배 피해","공격력이 항상 20 증가","치명타가 절대 발생하지 않음"],"answer":"1","aliases":["5회 중 1회","약 20퍼센트"]},
    {"category":"아포칼립스","q":"ABADDON 월드보스전에서 높은 기여도를 노리려면 무엇이 중요할까요?","choices":["꾸준히 공격해 누적 피해를 높인다","한 번도 참여하지 않는다","채팅만 한다","장비를 모두 해제한다"],"answer":"1","aliases":["누적 피해","꾸준히 공격"]},
    {"category":"아포칼립스","q":"ABADDON 세계에서 감염도가 높아졌을 때 가장 먼저 확인할 시설은?","choices":["병원","시장","카지노","경기장"],"answer":"1","aliases":["병원"]},
]


CORE_QUESTIONS = BASE_QUESTIONS
BASE_QUESTIONS = CORE_QUESTIONS + EXTRA_QUESTIONS
KST = ZoneInfo("Asia/Seoul")


# V2.0-8: 단순 사칙연산 자동 생성 문제는 제거하고 상식/생존/세계관 중심으로 구성합니다.

def _clean(text):
    raw = re.sub(r"\s+", "", str(text)).casefold()
    alnum = re.sub(r"[^0-9a-zA-Z가-힣]+", "", raw)
    return alnum if alnum else raw


def _seed(text):
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], 16)


def _answer_token(text):
    raw = str(text).strip()
    circled = {"①":"1", "②":"2", "③":"3", "④":"4"}
    if raw in circled:
        return circled[raw]
    compact = re.sub(r"\s+", "", raw)
    match = re.fullmatch(r"([1-4])(?:번|번답|번정답|번입니다)?[.!。]?", compact)
    if match:
        return match.group(1)
    return _clean(raw)


def validate_question(question):
    errors = []
    if not isinstance(question, dict):
        return ["문제 데이터가 객체가 아님"]
    text = str(question.get("q", "")).strip()
    category = str(question.get("category", "")).strip()
    choices = question.get("choices")
    answer = str(question.get("answer", "")).strip()
    if not text:
        errors.append("문제 문장 없음")
    if not category:
        errors.append("분류 없음")
    if not isinstance(choices, list) or len(choices) != 4:
        errors.append("보기 4개 아님")
        choices = choices if isinstance(choices, list) else []
    if answer not in {"1", "2", "3", "4"}:
        errors.append("정답 번호가 1~4가 아님")
    if choices:
        cleaned = [_clean(x) for x in choices]
        if any(not x for x in cleaned):
            errors.append("빈 보기 존재")
        if len(set(cleaned)) != len(cleaned):
            errors.append("중복 보기 존재")
    return errors


def audit_question_bank(pool):
    errors = []
    seen = {}
    categories = {}
    for idx, question in enumerate(pool, 1):
        q_errors = validate_question(question)
        if q_errors:
            errors.append({"index": idx, "question": str(question.get("q", ""))[:80] if isinstance(question, dict) else str(question)[:80], "errors": q_errors})
            continue
        key = _clean(question["q"])
        if key in seen:
            errors.append({"index": idx, "question": question["q"], "errors": [f"중복 문제 (#{seen[key]})"]})
        else:
            seen[key] = idx
        categories[question["category"]] = categories.get(question["category"], 0) + 1
    return {"total": len(pool), "errors": errors, "categories": categories}


def get_question_pool(world_data):
    custom = world_data.setdefault("custom_quizzes", [])
    valid_custom = [q for q in custom if not validate_question(q)]
    return BASE_QUESTIONS + valid_custom


def get_daily_quiz(world_data, guild_id, date_text):
    # 오늘 선택된 문제를 스냅샷으로 고정해 당일 관리자 추가/삭제로 정답이 바뀌지 않게 합니다.
    rotations = world_data.setdefault("daily_quiz_rotation", {})
    state = rotations.setdefault(str(guild_id), {})
    if state.get("date") == date_text and isinstance(state.get("question"), dict) and not validate_question(state["question"]):
        return deepcopy(state["question"]), bool(state.get("golden", False))

    pool = get_question_pool(world_data)
    if not pool:
        raise RuntimeError("퀴즈 문제은행이 비어 있습니다.")

    # 길드별로 문제 순서를 해시 정렬하고 날짜 순번으로 순환: 문제 수만큼 지나기 전에는 같은 문제가 반복되지 않습니다.
    ordered = sorted(pool, key=lambda q: _seed(f"quiz-order:{guild_id}:{_clean(q['category'])}:{_clean(q['q'])}"))
    day_number = datetime.strptime(date_text, "%Y-%m-%d").date().toordinal()
    question = deepcopy(ordered[day_number % len(ordered)])
    golden = (_seed(f"golden:{guild_id}:{date_text}") % 100) < 3
    state.clear()
    state.update({"date": date_text, "question": deepcopy(question), "golden": golden})
    return question, golden


def is_correct_answer(question, user_answer):
    answer = str(question["answer"])
    correct_choice = question["choices"][int(answer) - 1]
    accepted = [answer, correct_choice] + list(question.get("aliases", []))
    token = _answer_token(user_answer)
    return token in {_answer_token(x) for x in accepted}


def register_quiz_commands(bot, get_user, check_registered, save_data, world_data, send_pages, add_season_points=None):
    def get_pool():
        return get_question_pool(world_data)

    def today_info(guild_id):
        today = datetime.now(KST).strftime("%Y-%m-%d")
        question, golden = get_daily_quiz(world_data, guild_id, today)
        return today, question, golden

    @bot.command(name="오늘의퀴즈", aliases=["일일퀴즈"])
    async def daily_quiz(ctx):
        if not await check_registered(ctx):
            return
        today, q, golden = today_info(ctx.guild.id if ctx.guild else 0)
        save_data()  # 오늘 문제 스냅샷을 재시작 후에도 유지
        choices = "\n".join(f"{i}. {text}" for i, text in enumerate(q["choices"], 1))
        title = "🌟 황금 오늘의 퀴즈" if golden else "🧠 오늘의 퀴즈"
        food = 3000 if golden else 700
        exp = 1200 if golden else 350
        await ctx.send(
            f"{title} | `{q['category']}`\n\n"
            f"**Q. {q['q']}**\n{choices}\n\n"
            f"보상: 식량 **{food:,}개** + 경험치 **{exp:,}**\n"
            f"정답 입력: `!정답 번호` 또는 `!정답 답안`\n"
            f"오늘 정답을 맞힌 뒤에는 다시 보상을 받을 수 없습니다."
        )

    @bot.command(name="정답")
    async def answer_quiz(ctx, *, 답안: str):
        if not await check_registered(ctx):
            return
        u = get_user(ctx.author.id)
        today, q, golden = today_info(ctx.guild.id if ctx.guild else 0)
        quiz_state = u.setdefault("daily_quiz", {"date":"", "solved":False, "attempts":0, "correct":0, "total_correct":0})
        if quiz_state.get("date") != today:
            quiz_state.update({"date":today, "solved":False, "attempts":0, "correct":0})
        if quiz_state.get("solved"):
            await ctx.send("✅ 오늘의 퀴즈 보상은 이미 받았습니다.")
            return
        if quiz_state.get("attempts", 0) >= 3:
            await ctx.send("❌ 오늘은 정답 기회를 모두 사용했습니다. 내일 다시 도전하세요.")
            return

        quiz_state["attempts"] = quiz_state.get("attempts", 0) + 1
        correct = is_correct_answer(q, 답안)
        if not correct:
            remain = 3 - quiz_state["attempts"]
            save_data()
            suffix = " 정답은 퀴즈 마감 후 공개됩니다." if remain == 0 else ""
            await ctx.send(f"❌ 오답입니다. 남은 기회: **{remain}회**{suffix}")
            return

        food = 3000 if golden else 700
        exp = 1200 if golden else 350
        quiz_state["solved"] = True
        quiz_state["correct"] = 1
        quiz_state["total_correct"] = quiz_state.get("total_correct", 0) + 1
        u["balance"] = u.get("balance", 0) + food
        u["exp"] = u.get("exp", 0) + exp
        u.setdefault("stats", {}).setdefault("earned", 0)
        u["stats"]["earned"] += food
        if add_season_points:
            add_season_points(u, 25 if golden else 8)
        save_data()
        special = "\n🌟 황금 퀴즈 대박 보상!" if golden else ""
        answer_text = q["choices"][int(q["answer"]) - 1]
        await ctx.send(
            f"🎉 **정답입니다!**{special}\n"
            f"정답: **{q['answer']}번 · {answer_text}**\n"
            f"식량 **+{food:,}개** | 경험치 **+{exp:,}**\n"
            f"누적 정답: **{quiz_state['total_correct']}개**"
        )

    @bot.command(name="퀴즈랭킹")
    async def quiz_ranking(ctx):
        if not await check_registered(ctx):
            return
        rankings = []
        for member in ctx.guild.members:
            u = get_user(member.id)
            count = u.get("daily_quiz", {}).get("total_correct", 0)
            if count:
                rankings.append((count, member.display_name))
        rankings.sort(reverse=True)
        if not rankings:
            await ctx.send("📭 아직 누적 퀴즈 정답 기록이 없습니다.")
            return
        lines = [f"{i}. **{name}** — {count}개" for i, (count, name) in enumerate(rankings[:20], 1)]
        await ctx.send("🏆 **퀴즈 누적 랭킹**\n" + "\n".join(lines))

    @bot.command(name="퀴즈통계", aliases=["퀴즈정보", "quizstats"])
    async def quiz_stats(ctx):
        if not await check_registered(ctx):
            return
        u = get_user(ctx.author.id)
        state = u.get("daily_quiz", {})
        report = audit_question_bank(get_pool())
        custom_count = len(world_data.setdefault("custom_quizzes", []))
        await ctx.send(
            "📚 **ABADDON 퀴즈 문제은행**\n"
            f"기본 문제: **{len(BASE_QUESTIONS)}개** · 서버 추가: **{custom_count}개**\n"
            f"전체 사용 가능: **{report['total']}개** · 분류: **{len(report['categories'])}종**\n"
            f"내 누적 정답: **{int(state.get('total_correct', 0))}개**\n"
            "정답은 `!정답 1`, `!정답 1번`, `!정답 ①`, `!정답 답안` 모두 사용할 수 있습니다."
        )

    @bot.command(name="퀴즈검수", aliases=["퀴즈문제검수", "1802퀴즈검수", "quizaudit"])
    async def quiz_audit(ctx, 모드: str = ""):
        if not await require_admin(ctx):
            return
        base_report = audit_question_bank(BASE_QUESTIONS)
        full_report = audit_question_bank(get_pool())
        invalid_custom = len(world_data.setdefault("custom_quizzes", [])) - (full_report["total"] - len(BASE_QUESTIONS))
        status = "✅ 정상" if not base_report["errors"] and not full_report["errors"] and invalid_custom == 0 else "⚠️ 확인 필요"
        lines = [
            f"🧪 **ABADDON v18.0.2 퀴즈 문제은행 검수 — {status}**",
            f"기본 문제 **{len(BASE_QUESTIONS)}개** · 전체 사용 가능 **{full_report['total']}개**",
            f"분류 **{len(full_report['categories'])}종** · 기본 오류 **{len(base_report['errors'])}건** · 전체 오류 **{len(full_report['errors'])}건**",
            f"형식 불량 서버 퀴즈 **{invalid_custom}건**",
            "정답 파서: `1 / 1번 / ① / 정답 문구` 지원 ✅",
            "오늘 문제 스냅샷 고정 ✅ · KST 날짜 통일 ✅ · 자동 알림/직접 조회 동일 문제은행 ✅",
        ]
        if 모드.strip() in {"상세", "detail", "details"}:
            top_categories = sorted(full_report["categories"].items(), key=lambda x: (-x[1], x[0]))
            lines.append("\n**분류별 문제 수**\n" + " · ".join(f"{k} {v}" for k, v in top_categories))
            if full_report["errors"]:
                lines.append("\n**오류 예시**")
                for item in full_report["errors"][:8]:
                    lines.append(f"#{item['index']} {item['question']} — {', '.join(item['errors'])}")
        await ctx.send("\n".join(lines)[:1900])

    async def require_admin(ctx):
        if ctx.guild and (ctx.author == ctx.guild.owner or ctx.author.guild_permissions.administrator):
            return True
        await ctx.send("❌ 이 명령어는 관리자만 사용할 수 있습니다.")
        return False

    @bot.command(name="퀴즈추가")
    async def quiz_add(ctx, *, 내용: str):
        if not await require_admin(ctx):
            return
        # 형식: 문제 | 보기1 | 보기2 | 보기3 | 보기4 | 정답번호
        parts = [x.strip() for x in 내용.split("|")]
        if len(parts) != 6 or parts[5] not in {"1","2","3","4"}:
            await ctx.send("형식: `!퀴즈추가 문제 | 보기1 | 보기2 | 보기3 | 보기4 | 정답번호`")
            return
        candidate = {"category":"서버퀴즈", "q":parts[0], "choices":parts[1:5], "answer":parts[5]}
        candidate["aliases"] = [candidate["choices"][int(candidate["answer"]) - 1]]
        errors = validate_question(candidate)
        if errors:
            await ctx.send("❌ 퀴즈 추가 실패: " + ", ".join(errors))
            return
        pool = get_pool()
        if any(_clean(x.get("q", "")) == _clean(candidate["q"]) for x in pool):
            await ctx.send("⚠️ 같은 문장의 퀴즈가 이미 등록되어 있습니다.")
            return
        custom = world_data.setdefault("custom_quizzes", [])
        custom.append(candidate)
        save_data()
        await ctx.send(f"✅ 서버 퀴즈가 추가되었습니다. 사용자 퀴즈 번호: **{len(custom)}**")

    @bot.command(name="퀴즈삭제")
    async def quiz_delete(ctx, 번호: int):
        if not await require_admin(ctx):
            return
        custom = world_data.setdefault("custom_quizzes", [])
        if 번호 < 1 or 번호 > len(custom):
            await ctx.send("⚠️ 존재하지 않는 사용자 퀴즈 번호입니다.")
            return
        removed = custom.pop(번호 - 1)
        save_data()
        await ctx.send(f"🗑️ 퀴즈 삭제 완료: **{removed['q']}**")

    @bot.command(name="퀴즈목록")
    async def quiz_list(ctx):
        if not await require_admin(ctx):
            return
        custom = world_data.setdefault("custom_quizzes", [])
        if not custom:
            await ctx.send(f"📚 기본 퀴즈 **{len(BASE_QUESTIONS)}개**가 내장되어 있으며, 관리자 추가 퀴즈는 없습니다.")
            return
        lines = [f"{i}. {q['q']} (정답 {q['answer']}번)" for i, q in enumerate(custom, 1)]
        await send_pages(ctx.channel, f"📚 기본 퀴즈 **{len(BASE_QUESTIONS)}개** + 관리자 퀴즈 **{len(custom)}개**\n" + "\n".join(lines))


# v18.0.2 static registration marker
QUIZ_BANK_VERSION = "18.0.2"
