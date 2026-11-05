"""AIVLE Ⅺ: 깔끔한 사이드바 메뉴 UI + 멀티모달 분석 + TTS."""
import io
import re
import hashlib
import copy
import json
import secrets
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import streamlit as st
from openai import OpenAI
from PIL import Image, UnidentifiedImageError

from config import get_setting, llm_model, stt_model, tts_model
from prompts.system_prompts import CHAT_INSTRUCTIONS
from services.meeting_service import analyze_meeting, build_meeting_report
from services.task_service import STATUSES, make_briefing, personal_tasks, rank_tasks, with_ids
from services.speech_service import transcribe_audio, make_speech, SUPPORTED_AUDIO, MAX_AUDIO_BYTES
from services.email_service import parse_recipients, send_emails
from services.history_service import make_record, export_backup, import_backup, upsert_record
from services.calendar_service import save_event, deadline_entries, entries_for_day, month_html

st.set_page_config(page_title='AIVLE Ⅺ | AI 업무비서', page_icon='🤖', layout='wide', initial_sidebar_state='expanded')
ASSET_DIR = Path(__file__).resolve().parent / 'assets'
MAIN_IMAGE = ASSET_DIR / 'assistant_main.png'
SIDE_IMAGE = ASSET_DIR / 'assistant_side.png'

# Streamlit 공식 테마를 단일 진실 공급원으로 사용합니다.
# 앱의 오른쪽 위 메뉴 → Settings → Theme에서 Light / Dark를 전환합니다.
# 고정된 다크 색상이나 CSS 기반 가짜 테마 전환은 기본 위젯과 충돌합니다.

st.markdown("""<style>
/* AIVLE Ⅺ: native Streamlit theme colors, no hardcoded light/dark surface colors. */
.block-container {max-width: 1040px; padding-top: 1.35rem; padding-bottom: 3rem;}
.stApp h1, .stApp h2, .stApp h3 {letter-spacing: -.04em;}
.stApp h1 {font-size: 1.72rem !important;}
.stApp h2, .stApp h3 {font-size: 1.26rem !important;}
[data-testid="stVerticalBlockBorderWrapper"] > div {border-radius: 14px;}
[data-testid="stMetric"] {border: 1px solid var(--border-color, #8995a3); border-radius: 12px; padding: .8rem 1rem;}
/* Only the navigation group: don't accidentally restyle uploader, settings or other buttons. */
[data-testid="stSidebar"] .st-key-aivle_nav [data-testid="stVerticalBlock"] {gap: .12rem !important;}
[data-testid="stSidebar"] .st-key-aivle_nav [data-testid="stButton"] {margin: 0 !important;}
[data-testid="stSidebar"] .st-key-aivle_nav [data-testid="stButton"] button {
    width: 100% !important; min-height: 2.5rem !important; height: auto !important;
    display: flex !important; flex-direction: row !important;
    align-items: center !important; justify-content: flex-start !important;
    text-align: left !important; gap: .65rem !important;
    padding: .45rem .75rem !important; border-radius: 10px !important;
}
[data-testid="stSidebar"] .st-key-aivle_nav [data-testid="stButton"] button [data-testid="stMarkdownContainer"],
[data-testid="stSidebar"] .st-key-aivle_nav [data-testid="stButton"] button > div {
    text-align: left !important; flex: 0 1 auto !important;
    width: auto !important; margin: 0 !important;
}
[data-testid="stSidebar"] .st-key-aivle_nav [data-testid="stButton"] button p {
    text-align: left !important; margin: 0 !important;
}
[data-testid="stSidebar"] .st-key-aivle_nav [data-testid="stButton"] button svg {
    flex-shrink: 0 !important; color: currentColor !important;
}
/* Lightweight Google-style search hero and mascot speech bubble. */
/* Center the brand and mascot in a restrained homepage hero. */
.st-key-home_hero {max-width: 740px; margin: 7vh auto 1.4rem; padding: .3rem .2rem; text-align: center;}
.st-key-home_hero .aivle-home-wordmark {text-align:center !important; font-size: clamp(2.7rem, 6vw, 4.2rem) !important; font-weight: 720; letter-spacing: -.065em; margin: .2rem 0 1rem; line-height: 1.12;}
.st-key-home_hero .aivle-home-wordmark span {color: var(--primary-color);}
.st-key-home_hero .home_tagline {text-align:center; color: var(--text-color); opacity: .76; margin: 0 0 1.3rem;}
.st-key-aivle_fortune_line {text-align:center; max-width: 540px; margin: 0 auto .8rem; padding: .65rem 1rem; border-radius: 18px; border: 1px solid var(--border-color); background: var(--secondary-background-color);}
.st-key-aivle_fortune_line .aivle-fortune-title {font-size: .78rem; font-weight: 650; margin: 0 0 .25rem; color: var(--primary-color);}
.st-key-aivle_fortune_line p {font-size: .88rem; text-align:center; margin: 0;}
@media (max-width: 640px) {.st-key-home_hero {margin-top: 2rem;} .st-key-home_hero .aivle-home-wordmark {font-size:2.65rem !important;}}
/* One Google-style composer. Built-in plus, microphone, send share one input. */
.st-key-home_search_row {margin: 0 auto 1.2rem; max-width: 740px;}
.st-key-home_search_row [data-testid="stChatInput"] {
   border: 1.5px solid var(--border-color) !important; border-radius: 28px !important;
   box-shadow: 0 2px 12px color-mix(in srgb, var(--text-color) 7%, transparent);
}
.st-key-home_search_row [data-testid="stChatInput"] button {color: var(--text-color) !important;}
/* High-contrast controls in both themes. Avoid pale --border-color for icon outlines. */
.st-key-aivle_nav [data-testid="stButton"] button {
   border: 2px solid color-mix(in srgb, var(--text-color) 58%, transparent) !important;
   box-shadow: none !important;
}
.st-key-aivle_nav [data-testid="stButton"] button:not([kind="primary"]):not([data-testid="baseButton-primary"]) {
   background: var(--secondary-background-color) !important;
   color: var(--text-color) !important;
}
.st-key-aivle_nav [data-testid="stButton"] button:hover,
.st-key-aivle_nav [data-testid="stButton"] button:focus-visible {
   border-color: var(--primary-color) !important;
   box-shadow: 0 0 0 2px color-mix(in srgb, var(--primary-color) 22%, transparent) !important;
}
.st-key-aivle_nav button svg, .st-key-home_search_row [data-testid="stChatInput"] button svg {
   color: currentColor !important; fill: currentColor !important;
   stroke: currentColor !important; opacity: 1 !important;
}
.st-key-aivle_nav button svg {width: 19px !important; height: 19px !important;}
.st-key-home_search_row [data-testid="stChatInput"] {
   border: 2px solid color-mix(in srgb, var(--text-color) 60%, transparent) !important;
}
.st-key-home_search_row [data-testid="stChatInput"] button:not(:disabled) {
   color: var(--text-color) !important; opacity: 1 !important;
}
/* Keep a tiny, visible custom avatar without restoring the bulky old banner. */
.st-key-aivle_brand [data-testid="stImage"] img {border-radius: 6px; border: 1px solid color-mix(in srgb, var(--text-color) 40%, transparent); object-fit: cover;}
.st-key-aivle_cheer_bubble {position: relative; border-radius: 16px; background: var(--secondary-background-color);}
.st-key-aivle_cheer_bubble:before {content: ""; position:absolute; left:-7px; top:44%; width:12px; height:12px; transform:rotate(45deg); background: var(--secondary-background-color); border-left:1px solid var(--border-color); border-bottom:1px solid var(--border-color);}
/* The settings accordion, upload dropzone, popovers and inputs inherit the native theme. */
/* Calendar is custom HTML, so it must explicitly use native theme variables. */
.aivle-calendar {width: 100%; overflow-x: auto;}
.aivle-calendar table {width: 100%; min-width: 460px; table-layout: fixed;
    border-collapse: separate; border-spacing: 4px;}
.aivle-calendar th {text-align: center; font-size: .8rem;
    color: var(--text-color); opacity: .72; padding: 6px;}
.aivle-calendar td {height: 84px; vertical-align: top; padding: 8px;
    border: 1px solid var(--border-color, #8995a3); border-radius: 9px;
    background: var(--secondary-background-color); color: var(--text-color);}
.aivle-calendar td.other {opacity: .4;}
.aivle-calendar td.today {outline: 2px solid var(--primary-color); outline-offset: -2px;}
.aivle-calendar .day-number {font-weight: 650; margin-bottom: 8px;}
.aivle-calendar .event-dot, .aivle-calendar .task-dot {display: block; font-size: .69rem;
    margin-top: 3px; overflow: hidden; white-space: nowrap; text-overflow: ellipsis;}
.aivle-calendar .event-dot {color: var(--text-color); background: color-mix(in srgb, var(--primary-color) 12%, transparent); border-radius: 4px; padding: 2px 4px;}
.aivle-calendar .more-events {display: block; color: var(--text-color); opacity: .75; font-size: .68rem; margin-top: 3px;}
.aivle-calendar .task-dot {color: var(--primary-color); font-weight: 600;}
@media (max-width: 640px) {
    .aivle-calendar td {height: 70px; padding: 5px;}
    .block-container {padding-top: 1rem;}
}
</style>""", unsafe_allow_html=True)

DEFAULTS = {
    'analysis': None, 'tasks': [], 'messages': [], 'pending_email': None,
    'brief_audio': None, 'brief_audio_for': None, 'last_chat_audio': None,
    'last_transcript': '', 'last_chat_reply': '', 'owner': '김 대리',
    'auto_voice': False, 'last_chat_audio_for': None, 'email_results': [],
    'meeting_transcript': '', 'meeting_archive': [], 'active_meeting_id': None,
    'calendar_events': [], 'calendar_selected': None, 'calendar_offset': 0,
    'meeting_cheer': None,
    'user_profile_image': None,
    'profile_upload_version': 0,
}
for key, value in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value.copy() if isinstance(value, (dict, list)) else value

api_key = get_setting('OPENAI_API_KEY')
if not api_key:
    st.error('OPENAI_API_KEY가 없습니다. Streamlit Community Cloud의 앱 Secrets를 확인하세요.')
    st.stop()

@st.cache_resource(show_spinner=False)
def get_client(key):
    return OpenAI(api_key=key, timeout=45.0, max_retries=1)

client = get_client(api_key)
today = datetime.now(ZoneInfo('Asia/Seoul')).date()


def reset_meeting():
    st.session_state.analysis = None
    st.session_state.tasks = []
    st.session_state.brief_audio = None
    st.session_state.brief_audio_for = None
    st.session_state.pending_email = None
    st.session_state.meeting_transcript = ''
    st.session_state.email_results = []
    st.session_state.active_meeting_id = None
    st.session_state.meeting_cheer = None


def update_status(task_id):
    for task in st.session_state.tasks:
        if task['id'] == task_id:
            task['status'] = st.session_state[f'status_{task_id}']
            break
    st.session_state.brief_audio = None
    st.session_state.brief_audio_for = None
    if st.session_state.active_meeting_id and st.session_state.analysis:
        st.session_state.meeting_archive = upsert_record(
            st.session_state.meeting_archive, make_record(
                st.session_state.analysis, st.session_state.tasks,
                st.session_state.meeting_transcript,
                record_id=st.session_state.active_meeting_id,
            ), preserve_created=True
        )


def format_problem(exc):
    name = type(exc).__name__
    if name in ('AuthenticationError', 'PermissionDeniedError'):
        return 'API 인증 또는 권한 오류입니다. 키와 프로젝트 권한을 확인하세요.'
    if name == 'RateLimitError':
        return '요청 한도 또는 API 사용량 제한입니다. 잠시 후 다시 시도하세요.'
    if name in ('APITimeoutError', 'APIConnectionError', 'TimeoutError'):
        return 'API 서버 연결이 지연되거나 실패했습니다.'
    if isinstance(exc, (ValueError, UnicodeError, json.JSONDecodeError)):
        return str(exc)[:220]
    return f'요청 처리 실패 ({name}). 앱 로그를 확인하세요.'


def description_to_checklist(description):
    lines = [re.sub(r'^\s*(?:[-*•]\s*|\d+[.)]\s*)', '', x).strip()
             for x in (description or '').splitlines()]
    lines = [x for x in lines if x]
    return lines or ['업무 설명이 없습니다. 담당자에게 세부 내용을 확인하세요.']


def toggle_subtask(task_id, index):
    task = next((x for x in st.session_state.tasks if x.get('id') == task_id), None)
    if task is None:
        return
    checks = list(task.get('todo_done', []))
    lines = description_to_checklist(task.get('description'))
    checks = (checks + [False] * len(lines))[:len(lines)]
    checks[index] = bool(st.session_state[f"todo_{st.session_state.active_meeting_id or 'current'}_{task_id}_{index}"])
    task['todo_done'] = checks
    if all(checks):
        task['status'] = '완료'
    elif task.get('status') == '완료':
        task['status'] = '진행 중'
    elif any(checks) and task.get('status') == '미시작':
        task['status'] = '진행 중'
    st.session_state[f'status_{task_id}'] = task['status']
    st.session_state.brief_audio = None
    st.session_state.brief_audio_for = None
    if st.session_state.active_meeting_id and st.session_state.analysis:
        st.session_state.meeting_archive = upsert_record(
            st.session_state.meeting_archive,
            make_record(st.session_state.analysis, st.session_state.tasks,
                        st.session_state.meeting_transcript,
                        record_id=st.session_state.active_meeting_id), preserve_created=True)


CHEER_LINES = [
    '🌟 오늘의 행운 키워드는 협업! 서로의 생각을 나누면 좋은 일이 생길지도 몰라요.',
    '🍀 잘 정리된 회의 하나가 오늘의 여유를 만들어 줘요.',
    '🚀 작은 할 일부터 하나씩! 오늘도 충분히 잘하고 있어요.',
    '☀️ 오늘의 좋은 기운은 명확한 목표에서 시작돼요.',
    '💡 아이디어가 떠오르는 하루! 메모 한 줄도 놓치지 마세요.',
    '🌱 꾸준한 한 걸음이 큰 성과가 될 거예요.',
    '🎯 회의는 끝났고, 이제 실천할 차례! 응원할게요.',
]


def show_meeting_cheer():
    if st.session_state.meeting_cheer is None:
        st.session_state.meeting_cheer = secrets.choice(CHEER_LINES)
    with st.container(key='aivle_fortune_line'):
        st.markdown(
            '<p class="aivle-fortune-title">🍀 오늘의 운세</p>',
            unsafe_allow_html=True,
        )
        st.markdown(st.session_state.meeting_cheer)


with st.sidebar:
    # ── [요청사항] 사이드바 최상단 "AIVLE Ⅺ" 왼쪽에 작고 네모난 프로필 배치 ──
    with st.container(key='aivle_brand'):
        brand_avatar, brand_title = st.columns([1, 4], vertical_alignment='center', gap='small')
        with brand_avatar:
            if st.session_state.user_profile_image is not None:
                try:
                    img = Image.open(io.BytesIO(st.session_state.user_profile_image))
                    st.image(img, width=32)
                except Exception:
                    st.markdown("👤")
            else:
                st.markdown("👤")
        with brand_title:
            st.markdown('**AIVLE Ⅺ**')

    st.divider()

    menu_icons = [
        ('홈', ':material/home:'),
        ('회의록', ':material/folder_open:'),
        ('캘린더', ':material/calendar_month:'),
        ('할 일', ':material/checklist:'),
        ('브리핑', ':material/assignment:'),
    ]
    legacy_pages = {
        '회의 통합 분석': '홈', 'AI 비서 대화': '홈',
        '회의 기록': '회의록', '담당 업무': '할 일',
        '업무 브리핑': '브리핑',
    }
    previous_page = st.session_state.get('active_page', '홈')
    st.session_state.active_page = legacy_pages.get(previous_page, previous_page)
    if st.session_state.active_page not in [name for name, _ in menu_icons]:
        st.session_state.active_page = '홈'
    with st.container(key='aivle_nav'):
        for menu_index, (name, icon) in enumerate(menu_icons):
            if st.button(name, icon=icon,
                         type='primary' if st.session_state.active_page == name else 'secondary',
                         key=f'nav_{menu_index}', use_container_width=True):
                st.session_state.active_page = name
                st.rerun()
    page = st.session_state.active_page
    st.divider()
    st.caption(f'미완료 업무 {sum(t.get("status") != "완료" for t in st.session_state.tasks)}건 · 저장된 회의 {len(st.session_state.meeting_archive)}건')
    
    # ── 설정 영역 (마스코트 설정 제거, 프로필 관리 기능만 남김) ──
    with st.expander('⚙️ 설정', expanded=False):
        st.caption('🎨 화면 테마: 오른쪽 위 ⋮ 메뉴 → Settings → Theme에서 Light / Dark를 선택하세요.')
        st.markdown('**내 프로필 사진 관리**')
        st.caption('사이드바 상단에 표시될 본인의 프로필 사진을 등록하세요.')
        
        profile_upload = st.file_uploader(
            '프로필 사진 선택 (PNG / JPG)', 
            type=['png', 'jpg', 'jpeg'],
            key=f"user_profile_upload_{st.session_state.get('profile_upload_version', 0)}",
            max_upload_size=3,
            help='최대 3MB · 세션에만 저장'
        )
        
        if profile_upload is not None:
            try:
                profile_data = profile_upload.getvalue()
                if len(profile_data) > 3_000_000:
                    raise ValueError('이미지는 3MB 이하여야 합니다.')
                with Image.open(io.BytesIO(profile_data)) as check_img:
                    if check_img.format not in ('PNG', 'JPEG'):
                        raise ValueError('PNG 또는 JPG 이미지만 지원합니다.')
                    check_img.verify()
                st.session_state.user_profile_image = profile_data
                st.rerun()
            except (OSError, ValueError, UnidentifiedImageError) as exc:
                st.error('프로필 이미지 오류: ' + str(exc)[:120])
                
        if st.session_state.user_profile_image is not None:
            col_p1, col_p2 = st.columns([1, 2], vertical_alignment='center')
            with col_p1:
                st.image(st.session_state.user_profile_image, width=42)
            with col_p2:
                if st.button('프로필 사진 삭제', key='reset_profile_img', use_container_width=True):
                    st.session_state.user_profile_image = None
                    st.session_state.profile_upload_version += 1
                    st.rerun()
        else:
            st.caption('등록된 프로필 사진이 없습니다.')

        st.divider()
        st.text_input('담당자 이름', key='owner', help='회의록의 담당자 표기와 같게 입력하세요.')
        st.caption(f'기준일 {today.isoformat()} · 한국 시간')
        st.toggle('AI 답변 자동 음성 생성', key='auto_voice', help='답변마다 TTS API를 호출하므로 비용이 추가됩니다.')
        st.caption(f'최근 대화 {len(st.session_state.messages) // 2}/10')
        st.caption('OpenAI: 설정됨' if api_key else 'OpenAI: 설정 필요')
        st.caption('Gmail: 설정됨' if get_setting('GMAIL_ADDRESS') and get_setting('GMAIL_APP_PASSWORD') else 'Gmail: 설정 필요')
        if st.button('새 대화 시작', use_container_width=True):
            st.session_state.messages = []
            st.session_state.last_transcript = ''
            st.session_state.last_chat_reply = ''
            st.session_state.last_chat_audio = None
            st.session_state.last_chat_audio_for = None
            st.rerun()
        if st.button('회의/업무 데이터 초기화', use_container_width=True):
            reset_meeting()
            st.rerun()
    st.caption('회의·일정은 현재 세션에 저장됩니다. 영구 보관은 [회의록]에서 JSON 백업을 사용하세요.')

page_kicker = {
    '회의록': 'MEETING ARCHIVE',
    '캘린더': 'CALENDAR',
    '할 일': 'TASKS',
    '브리핑': 'DAILY BRIEFING',
}
if page == '홈':
    with st.container(key='home_hero'):
        st.markdown('<h1 class="aivle-home-wordmark">AIVLE <span>Ⅺ</span></h1>', unsafe_allow_html=True)
        st.markdown('<p class="home_tagline">회의부터 일정까지, 무엇이든 도와드릴게요.</p>', unsafe_allow_html=True)
        show_meeting_cheer()
else:
    st.caption(page_kicker.get(page, 'AIVLE Ⅺ'))
    st.title(page)

if page == '홈':
    with st.container(key='home_search_row'):
        home_submission = st.chat_input(
            '궁금한 것을 입력하세요', key='home_unified_composer',
            accept_file='multiple',
            file_type=['txt', 'png', 'jpg', 'jpeg', 'mp3', 'm4a', 'mp4',
                       'mpeg', 'mpga', 'wav', 'webm'],
            accept_audio=True, max_upload_size=24,
        )
    home_question = None
    if home_submission is not None:
        submitted_text = (home_submission.text or '').strip()
        attached_files = list(home_submission.files or [])
        recorded_voice = home_submission.audio
        if attached_files:
            text_files = [f for f in attached_files if f.name.lower().endswith('.txt')]
            image_files = [f for f in attached_files if f.name.lower().endswith(('.png', '.jpg', '.jpeg'))]
            sound_files = [f for f in attached_files if f.name.lower().endswith(('.mp3', '.m4a', '.mp4', '.mpeg', '.mpga', '.wav', '.webm'))]
            issue = None
            if len(image_files) > 1 or len(sound_files) > 1 or (sound_files and recorded_voice):
                issue = '이미지와 녹음 파일은 각각 1개씩 첨부해 주세요. 마이크 녹음과 음성 파일 중 하나를 선택해 주세요.'
            elif any(len(f.getvalue()) > 1_000_000 for f in text_files):
                issue = 'TXT는 파일당 1MB 이하여야 합니다.'
            elif any(len(f.getvalue()) > 8_000_000 for f in image_files):
                issue = '이미지는 8MB 이하여야 합니다.'
            elif any(len(f.getvalue()) > MAX_AUDIO_BYTES for f in sound_files):
                issue = '음성 파일은 24MB 이하여야 합니다.'
            if issue:
                st.warning(issue)
            else:
                try:
                    meeting_text = '\n\n'.join(f'[{f.name}]\n' + f.getvalue().decode('utf-8-sig') for f in text_files)
                    image_data, image_mime = None, None
                    if image_files:
                        image_data = image_files[0].getvalue()
                        with Image.open(io.BytesIO(image_data)) as img:
                            fmt = img.format
                            if fmt not in ('PNG', 'JPEG'):
                                raise ValueError('PNG 또는 JPEG 형식의 이미지만 사용할 수 있어요.')
                            img.verify()
                        image_mime = 'image/png' if fmt == 'PNG' else 'image/jpeg'
                    audio_file = sound_files[0] if sound_files else recorded_voice
                    transcript_text = ''
                    if audio_file is not None:
                        if len(audio_file.getvalue()) > MAX_AUDIO_BYTES:
                            raise ValueError('음성 녹음은 24MB 이하여야 합니다.')
                        with st.spinner('회의 음성을 전사하고 있어요...'):
                            transcript_text = transcribe_audio(
                                client, stt_model(), audio_file.getvalue(),
                                audio_file.name if sound_files else 'meeting_recording.wav')
                    combined = meeting_text.strip()
                    if transcript_text:
                        combined += ('\n\n' if combined else '') + '[회의 녹음 전사]\n' + transcript_text
                    if submitted_text:
                        combined += ('\n\n' if combined else '') + '[사용자 요청]\n' + submitted_text
                    with st.spinner('회의 자료를 분석하고 할 일을 정리하고 있어요...'):
                        analysis = analyze_meeting(client, llm_model(), combined, image_data, image_mime)
                    reset_meeting()
                    st.session_state.analysis = analysis
                    st.session_state.tasks = with_ids(analysis.get('tasks', []))
                    st.session_state.meeting_transcript = transcript_text
                    record = make_record(analysis, st.session_state.tasks, transcript_text)
                    st.session_state.meeting_archive = upsert_record(st.session_state.meeting_archive, record)
                    st.session_state.active_meeting_id = record['id']
                    st.session_state.meeting_cheer = secrets.choice(CHEER_LINES)
                    st.success(f'회의 분석 완료 · 할 일 {len(st.session_state.tasks)}개 · 회의록에 저장했어요.')
                except (UnicodeError, ValueError, UnidentifiedImageError, OSError) as exc:
                    st.error('첨부 자료 확인: ' + str(exc)[:180])
                except Exception as exc:
                    st.error(format_problem(exc))
        elif recorded_voice is not None:
            try:
                if len(recorded_voice.getvalue()) > MAX_AUDIO_BYTES:
                    raise ValueError('음성 질문은 24MB 이하여야 합니다.')
                with st.spinner('음성 질문을 텍스트로 변환하고 있어요...'):
                    home_question = transcribe_audio(client, stt_model(), recorded_voice.getvalue(), 'voice.wav')
                st.session_state.last_transcript = home_question
                if submitted_text:
                    home_question = submitted_text + '\n' + home_question
                st.info('인식한 질문: ' + (home_question or '음성을 인식하지 못했어요.'))
            except Exception as exc:
                st.error(format_problem(exc))
        else:
            home_question = submitted_text

    if st.session_state.meeting_transcript:
        with st.expander('🎙️ 회의 녹음 전사 결과 확인'):
            st.caption('자동 음성 인식 결과에는 오류가 있을 수 있어 원본 녹음과 대조해 주세요.')
            st.text(st.session_state.meeting_transcript)
            st.download_button('전사 텍스트 다운로드', st.session_state.meeting_transcript,
                               'meeting_transcript.txt', mime='text/plain')

    if st.session_state.analysis:
        info = st.session_state.analysis
        st.subheader('📋 회의 분석 결과')
        st.markdown('**' + str(info.get('meeting_title', '통합 회의록')) + '**')
        st.write(info.get('summary', ''))
        a, b, c = st.columns(3)
        a.metric('추출 업무', len(st.session_state.tasks))
        b.metric('확정 결정', len(info.get('decisions', [])))
        c.metric('확인 필요', len(info.get('conflicts', [])))
        with st.expander('확정 결정사항', expanded=True):
            for item in info.get('decisions', []):
                st.markdown('- ' + item)
        with st.expander('검토 중인 사항'):
            for item in info.get('pending', []):
                st.markdown('- ' + item)
        with st.expander('자료 간 불일치 / 확인 필요'):
            for item in info.get('conflicts', []):
                st.warning(item)
        report = build_meeting_report(info, st.session_state.tasks)
        st.download_button('최종 회의록 다운로드 (.md)', report, 'final_meeting_report.md', mime='text/markdown')
        with st.expander('최종 회의록 텍스트 보기'):
            st.markdown(report)
    else:
        pass

elif page == '회의록':
    st.caption('🗂️ 회의별 핵심 요약과 담당 업무를 확인하고, 필요할 때 다시 열 수 있습니다.')
    archive = st.session_state.meeting_archive
    total_tasks = sum(len(r.get('tasks', [])) for r in archive)
    active_tasks = sum(t.get('status') != '완료' for r in archive for t in r.get('tasks', []))
    m1, m2, m3 = st.columns(3)
    m1.metric('📁 저장된 회의', f'{len(archive)}건')
    m2.metric('📋 추출된 업무', f'{total_tasks}건')
    m3.metric('⏳ 미완료 업무', f'{active_tasks}건')
    st.info('💾 기록은 현재 브라우저 세션에만 유지됩니다. 중요한 회의는 JSON 백업을 다운로드해 주세요. 원본 음성·사진은 보관하지 않습니다.')
    backup_json = export_backup(archive, st.session_state.messages, st.session_state.calendar_events)
    col_backup, col_restore = st.columns([2, 1], vertical_alignment='bottom')
    with col_backup:
        st.download_button('⬇️ 회의·일정·대화 백업 (JSON)', backup_json,
                           file_name=f'aivle_xi_backup_{today.isoformat()}.json',
                           mime='application/json', use_container_width=True)
    with col_restore:
        with st.popover('📥 백업 복원', use_container_width=True):
            restore_file = st.file_uploader('AIVLE Ⅺ 백업 JSON', type=['json'], key='history_restore_file', max_upload_size=10)
            if st.button('백업 불러오기', disabled=restore_file is None):
                try:
                    records, messages, events = import_backup(restore_file.getvalue(), include_events=True)
                    st.session_state.meeting_archive = records
                    st.session_state.messages = messages
                    st.session_state.calendar_events = events
                    reset_meeting()
                    st.rerun()
                except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                    st.error('백업 복원 실패: ' + str(exc)[:150])

    st.divider()
    if archive:
        search_col, sort_col = st.columns([3, 2])
        with search_col:
            keyword = st.text_input('🔎 회의 검색', placeholder='회의 제목, 요약, 담당자 검색')
        with sort_col:
            sort_choice = st.selectbox('정렬 기준', ['최근 저장순', '오래된 저장순', '회의일 최신순'])
        def searchable(record):
            info = record.get('analysis') or {}
            texts = [record.get('title', ''), info.get('summary', '')]
            texts += [str(t.get('owner','')) + ' ' + str(t.get('title','')) for t in record.get('tasks', [])]
            return ' '.join(str(x) for x in texts).casefold()
        filtered = [r for r in archive if keyword.casefold().strip() in searchable(r)]
        if sort_choice == '최근 저장순':
            filtered.sort(key=lambda r: r.get('saved_at',''), reverse=True)
        elif sort_choice == '오래된 저장순':
            filtered.sort(key=lambda r: r.get('saved_at',''))
        else:
            filtered.sort(key=lambda r: r.get('meeting_date') or '', reverse=True)
        st.caption(f'검색 결과 {len(filtered)}건 / 전체 {len(archive)}건')
        if not filtered:
            st.info('검색 조건과 일치하는 회의가 없습니다.')
        for record in filtered:
            info = record.get('analysis') or {}
            tasks = record.get('tasks', [])
            pending = [t for t in tasks if t.get('status') != '완료']
            decisions = info.get('decisions', []) or []
            conflicts = info.get('conflicts', []) or []
            with st.container(border=True):
                st.markdown('### 📑 ' + str(record.get('title') or '제목 없는 회의'))
                st.caption(f"🗓️ 회의일: {record.get('meeting_date') or '미상'} · 💾 저장: {str(record.get('saved_at',''))[:16].replace('T',' ')}")
                st.write(info.get('summary') or '요약이 없습니다.')
                st.caption(f'✅ 결정 {len(decisions)}건  | 📋 업무 {len(tasks)}건  | ⏳ 미완료 {len(pending)}건  | ⚠️ 확인 필요 {len(conflicts)}건')
                if decisions:
                    st.markdown('**✅ 주요 결정사항**')
                    for decision in decisions[:3]:
                        st.markdown('• ' + str(decision))
                    if len(decisions) > 3:
                        st.caption(f'그 외 {len(decisions)-3}건은 전체 회의록에서 확인하세요.')
                if conflicts:
                    st.warning('⚠️ 자료 간 불일치 또는 확인 필요: ' + str(conflicts[0]))
                if pending:
                    with st.expander(f'📋 미완료 업무 미리보기 ({len(pending)}건)'):
                        for task in pending[:10]:
                            st.markdown(f"- **{task.get('title','제목 없음')}** · {task.get('owner','담당 미정')} · 마감 {task.get('due_date') or '미정'}")
                actions = st.columns([1.15, 1.15, .8])
                if actions[0].button('📂 회의 불러오기', key=f"load_{record['id']}", use_container_width=True):
                    st.session_state.analysis = copy.deepcopy(info)
                    st.session_state.tasks = copy.deepcopy(tasks)
                    st.session_state.meeting_transcript = record.get('transcript','')
                    st.session_state.active_meeting_id = record['id']
                    st.session_state.brief_audio = None
                    st.session_state.brief_audio_for = None
                    st.session_state.pending_email = None
                    for task in st.session_state.tasks:
                        st.session_state[f"status_{task['id']}"] = task.get('status', '미시작')
                    st.session_state.active_page = '할 일'
                    st.rerun()
                report = build_meeting_report(info, tasks)
                actions[1].download_button('📥 회의록 저장', report,
                                        file_name=f"meeting_{record['id']}.md", mime='text/markdown',
                                        key=f"dl_{record['id']}", use_container_width=True)
                if actions[2].button('🗑️ 삭제', key=f"del_{record['id']}", use_container_width=True):
                    st.session_state.meeting_archive = [r for r in archive if r['id'] != record['id']]
                    if st.session_state.active_meeting_id == record['id']:
                        reset_meeting()
                    st.rerun()
                with st.expander('📄 전체 회의록 보기'):
                    st.markdown(report)
                if record.get('transcript'):
                    with st.expander('🎙️ 회의 음성 전사 보기'):
                        st.text(record['transcript'])
    else:
        st.info('📭 저장된 회의가 없습니다. 홈에서 첫 회의를 분석해 보세요.')

elif page == '캘린더':
    from datetime import date as calendar_date
    import calendar as calendar_lib

    st.caption('➕ 아래에서 직접 일정을 등록하세요. 저장한 일정 제목이 날짜 칸에 표시됩니다. Google Calendar와는 연결되지 않습니다.')
    deadlines = deadline_entries(
        st.session_state.meeting_archive,
        st.session_state.analysis,
        st.session_state.tasks,
        st.session_state.active_meeting_id,
    )
    events = st.session_state.calendar_events
    base = today.year * 12 + today.month - 1 + st.session_state.calendar_offset
    year, zero_month = divmod(base, 12)
    month = zero_month + 1
    pending_day = st.session_state.pop('cal_pending_date', None)
    if pending_day is not None:
        st.session_state.cal_day_select = pending_day
    chosen = st.date_input('일정 날짜 선택 및 상세 확인', value=today, key='cal_day_select')
    if st.session_state.pop('calendar_notice', None):
        st.success('일정이 등록됐습니다. 아래 달력에 제목이 표시됩니다.')
    st.subheader('➕ 일정 직접 추가')
    with st.form('calendar_add_form', clear_on_submit=True):
        add_title = st.text_input('일정 제목', max_chars=120, placeholder='예: 프로젝트 팀 회의')
        add_day = st.date_input('날짜', value=chosen)
        add_timed = st.checkbox('시작 시간 지정', value=False)
        add_time = st.time_input('시작 시간 (시간 미지정 시 무시)', value=datetime.now(ZoneInfo('Asia/Seoul')).time())
        add_note = st.text_area('메모 (선택)', max_chars=2000)
        add_submit = st.form_submit_button('➕ 일정 저장', type='primary', use_container_width=True)
    if add_submit:
        try:
            st.session_state.calendar_events = save_event(
                st.session_state.calendar_events,
                {'title': add_title, 'date': add_day.isoformat(),
                 'time': add_time.strftime('%H:%M') if add_timed else '', 'note': add_note}
            )
            st.session_state.calendar_offset = (add_day.year - today.year) * 12 + add_day.month - today.month
            st.session_state.cal_pending_date = add_day
            st.session_state.calendar_notice = f'✅ {add_day.isoformat()} · {add_title.strip()} 일정이 등록됐습니다.'
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
    st.divider()
    left, center, right = st.columns([1, 4, 1], vertical_alignment='center')
    with left:
        if st.button('◀ 이전', key='cal_prev', use_container_width=True):
            st.session_state.calendar_offset -= 1
            st.rerun()
    with center:
        st.markdown(f'<h3 style="text-align:center; margin:0">{year}년 {month}월</h3>', unsafe_allow_html=True)
    with right:
        if st.button('다음 ▶', key='cal_next', use_container_width=True):
            st.session_state.calendar_offset += 1
            st.rerun()
    st.markdown(month_html(year, month, events, deadlines, today), unsafe_allow_html=True)
    st.caption('🗓 직접 등록 일정 제목은 날짜 칸에 표시되며, 📌 표시는 업무 마감일입니다. 날짜를 선택하면 아래에서 상세 내용을 확인할 수 있습니다.')
    day_entries = entries_for_day(events, deadlines, chosen)
    st.subheader(f'📆 {chosen.isoformat()} 일정 ({len(day_entries)}건)')
    if not day_entries:
        st.info('선택한 날짜에 일정이 없습니다.')
    for entry in day_entries:
        if entry['kind'] == 'deadline':
            with st.container(border=True):
                st.markdown(f"**📌 {entry['title']}** · {entry.get('status','미시작')}")
                st.caption(f"회의: {entry.get('meeting','')} · 담당: {entry.get('owner','')}")
        else:
            with st.container(border=True):
                st.markdown(f"**🗓️ {entry.get('time','') or '종일'} · {entry['title']}**")
                if entry.get('note'):
                    st.caption(entry['note'])
    if events:
        with st.expander('✏️ 일정 수정·삭제'):
            chosen_id = st.selectbox('편집할 일정', options=[e['id'] for e in events],
                format_func=lambda key: next(f"{e['date']} · {e['title']}" for e in events if e['id']==key))
            selected_event = next(e for e in events if e['id'] == chosen_id)
            with st.form(f'calendar_edit_{chosen_id}'):
                edit_title = st.text_input('제목', value=selected_event['title'], max_chars=120)
                edit_day = st.date_input('날짜', value=calendar_date.fromisoformat(selected_event['date']))
                edit_time = st.text_input('시간 (HH:MM 또는 빈칸)', value=selected_event.get('time',''))
                edit_note = st.text_area('메모', value=selected_event.get('note',''), max_chars=2000)
                edit_save = st.form_submit_button('수정 저장', type='primary')
                edit_delete = st.form_submit_button('일정 삭제')
            if edit_save:
                try:
                    st.session_state.calendar_events = save_event(events,
                        {'id':chosen_id,'title':edit_title,'date':edit_day.isoformat(),
                         'time':edit_time.strip(),'note':edit_note})
                    st.success('일정을 수정했습니다.')
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
            if edit_delete:
                st.session_state.calendar_events = [e for e in events if e['id'] != chosen_id]
                st.success('일정을 삭제했습니다.')
                st.rerun()
    st.caption('직접 등록 일정은 세션에서만 유지됩니다. 회의록 메뉴의 JSON 백업에 일정도 함께 포함됩니다.')

elif page == '할 일':
    if not st.session_state.analysis:
        st.info('먼저 홈에서 자료를 분석해 주세요.')
    else:
        ranked = rank_tasks(st.session_state.tasks, today)
        mine = personal_tasks(ranked, st.session_state.owner)
        pending = [x for x in mine if x['status'] != '완료']
        m1, m2, m3 = st.columns(3)
        m1.metric('전체 업무', len(mine))
        m2.metric('미완료', len(pending))
        m3.metric('마감 임박/초과', len([x for x in pending if x['days_left'] is not None and x['days_left'] <= 2]))
        st.caption('우선순위 = 마감 긴급도 60점 + 중요도 25점 + 선행작업 15점 · AI 추정치는 확인 필요')
        show_all = st.checkbox('모든 담당자의 업무 표시')
        for task in (ranked if show_all else mine):
            with st.container(border=True):
                left, right = st.columns([3, 1], vertical_alignment='center')
                left.markdown('**' + task['title'] + '**')
                left.caption(f"담당 {task['owner']} · 마감 {task['due_date'] or '미정'} · {task['urgency_status']} · {task['priority_score']}점")
                status_key = f"status_{task['id']}"
                if status_key not in st.session_state:
                    st.session_state[status_key] = task.get('status', '미시작')
                right.selectbox('진행 상태', STATUSES, key=status_key, on_change=update_status, args=(task['id'],))
                st.markdown('**세부 할 일**')
                steps = description_to_checklist(task.get('description'))
                task_ref = next((x for x in st.session_state.tasks if x.get('id'] == task['id']), None)
                if task_ref is not None:
                    checked = (list(task_ref.get('todo_done', [])) + [False] * len(steps))[:len(steps)]
                    for i, item in enumerate(steps):
                        ck = f'todo_{st.session_state.active_meeting_id or "current"}_{task["id"]}_{i}'
                        if ck not in st.session_state:
                            st.session_state[ck] = checked[i]
                        st.checkbox(item, key=ck, on_change=toggle_subtask, args=(task['id'],i))
                    st.caption(f'완료 {sum(checked)}/{len(steps)} · 세부 할 일은 원문 설명을 줄 단위로 표시합니다.')
                with st.expander('근거 및 업무 원문'):
                    st.caption(task.get('source_notes', ''))
                    st.write(task.get('description',''))
        if not (ranked if show_all else mine):
            st.warning('담당 업무를 찾지 못했습니다. 설정에서 담당자 이름을 확인해 주세요.')

elif page == '브리핑':
    if not st.session_state.analysis:
        st.info('회의 분석 후 오늘의 업무 브리핑을 이용할 수 있습니다.')
    else:
        briefing = make_briefing(st.session_state.tasks, st.session_state.owner, today)
        with st.container(border=True):
            st.markdown(briefing)
        col1, col2 = st.columns(2)
        with col1:
            st.download_button('브리핑 다운로드', briefing, 'today_briefing.md', mime='text/markdown', use_container_width=True)
        with col2:
            listen = st.button('🔊 브리핑 음성 재생', use_container_width=True)
        if listen:
            try:
                with st.spinner('브리핑 음성 생성 중...'):
                    if st.session_state.brief_audio_for != briefing:
                        st.session_state.brief_audio = make_speech(client, tts_model(), briefing)
                        st.session_state.brief_audio_for = briefing
            except Exception as exc:
                st.error(format_problem(exc))
        if st.session_state.brief_audio is not None and st.session_state.brief_audio_for == briefing:
            st.audio(st.session_state.brief_audio, format='audio/mp3', autoplay=listen)

if page == '홈':
    if st.session_state.messages:
        st.divider()
    for message in st.session_state.messages[-20:]:
        with st.chat_message(message['role']):
            st.markdown(message['content'])
    user_question = home_question
    if user_question and user_question.strip():
        question = user_question.strip()
        if len(question) > 2500:
            st.warning('질문은 최대 2,500자까지 입력할 수 있습니다.')
        else:
            st.session_state.last_chat_audio = None
            st.session_state.last_chat_audio_for = None
            email_intent = ('메일' in question or '이메일' in question) and any(w in question for w in ('보내', '전송', '공유'))
            if email_intent:
                if st.session_state.analysis:
                    report = build_meeting_report(st.session_state.analysis, st.session_state.tasks)
                    brief = make_briefing(st.session_state.tasks, st.session_state.owner, today)
                    kind = '오늘의 브리핑' if ('브리핑' in question or '오늘 할 일' in question) else '통합 회의록'
                    content = brief if kind == '오늘의 브리핑' else report
                    st.session_state.pending_email = {'to': '', 'subject': f'[AIVLE Ⅺ] {kind}', 'body': content}
                    answer = '이메일 초안을 준비했습니다. 아래 공유 영역에서 확인 후 전송할 수 있습니다.'
                else:
                    answer = '회의 분석을 먼저 진행한 후 이메일을 준비할 수 있습니다.'
            else:
                try:
                    context = json.dumps({'calendar_events': st.session_state.calendar_events[:60]}, ensure_ascii=False)
                    if st.session_state.analysis:
                        context = json.dumps({
                            'summary': st.session_state.analysis.get('summary'),
                            'decisions': st.session_state.analysis.get('decisions'),
                            'pending': st.session_state.analysis.get('pending'),
                            'conflicts': st.session_state.analysis.get('conflicts'),
                            'my_tasks': personal_tasks(rank_tasks(st.session_state.tasks, today), st.session_state.owner),
                            'calendar_events': st.session_state.calendar_events[:60],
                        }, ensure_ascii=False)[:14000]
                    with st.spinner('답변 생성 중...'):
                        response = client.responses.create(
                            model=llm_model(),
                            instructions=CHAT_INSTRUCTIONS + f'\n사용자: {st.session_state.owner}\n오늘: {today}\n참고 업무 정보: {context}',
                            input=[*st.session_state.messages[-20:], {'role': 'user', 'content': question}],
                            max_output_tokens=1000,
                        )
                    answer = response.output_text.strip() or '응답이 비어 있습니다. 다시 질문해 주세요.'
                except Exception as exc:
                    answer = '답변 생성 실패: ' + format_problem(exc)
            st.session_state.messages.extend([{'role': 'user', 'content': question}, {'role': 'assistant', 'content': answer}])
            st.session_state.messages = st.session_state.messages[-20:]
            st.session_state.last_chat_reply = answer
            if st.session_state.auto_voice and not answer.startswith('답변 생성 실패:'):
                try:
                    with st.spinner('답변 음성 생성 중...'):
                        st.session_state.last_chat_audio = make_speech(client, tts_model(), answer)
                        st.session_state.last_chat_audio_for = answer
                except Exception as exc:
                    st.session_state.last_chat_audio = None
                    st.session_state.last_chat_audio_for = None
                    st.warning('텍스트 답변은 생성했지만 음성 생성에 실패했습니다: ' + format_problem(exc))
            st.rerun()
    if st.session_state.last_chat_reply:
        with st.container(border=True):
            st.markdown('**🔊 AIVLE Ⅺ의 답변 음성으로 듣기**')
            st.caption('재생 버튼을 누르면 MP3를 만들고 플레이어에 표시합니다. 브라우저가 자동 재생을 차단하면 ▶ 버튼을 눌러 주세요.')
            play_reply = st.button('🔊 마지막 답변 음성 생성 / 재생', use_container_width=True)
            if play_reply:
                try:
                    with st.spinner('음성 답변을 생성하고 있습니다...'):
                        if (st.session_state.last_chat_audio_for != st.session_state.last_chat_reply
                                or not st.session_state.last_chat_audio):
                            st.session_state.last_chat_audio = make_speech(
                                client, tts_model(), st.session_state.last_chat_reply)
                            st.session_state.last_chat_audio_for = st.session_state.last_chat_reply
                except Exception as exc:
                    st.session_state.last_chat_audio = None
                    st.session_state.last_chat_audio_for = None
                    st.error('TTS 생성 실패: ' + format_problem(exc))
            if (st.session_state.last_chat_audio
                    and st.session_state.last_chat_audio_for == st.session_state.last_chat_reply):
                st.audio(st.session_state.last_chat_audio, format='audio/mp3', autoplay=play_reply)
                st.download_button('MP3 음성 다운로드', st.session_state.last_chat_audio,
                                   'aivle_reply.mp3', mime='audio/mpeg')
            else:
                st.caption('아직 생성된 음성 파일이 없습니다. 위 버튼을 눌러 주세요.')

with st.sidebar:
    with st.expander('✉️ 이메일 공유', expanded=bool(st.session_state.pending_email)):
        if not st.session_state.analysis:
            st.info('회의 분석이 완료되면 이메일 공유가 활성화됩니다.')
        else:
            kind = st.radio('공유할 문서', ['최종 회의록', '오늘의 브리핑', '둘 다'], horizontal=True)
            if st.button('이메일 초안 작성'):
                report = build_meeting_report(st.session_state.analysis, st.session_state.tasks)
                brief = make_briefing(st.session_state.tasks, st.session_state.owner, today)
                content = {'최종 회의록': report, '오늘의 브리핑': brief, '둘 다': report + '\n\n---\n\n' + brief}[kind]
                st.session_state.pending_email = {'to': '', 'subject': f'[AIVLE Ⅺ] {kind}', 'body': content}
                st.session_state.email_results = []
            if st.session_state.pending_email is not None:
                with st.form('email_confirm_form', clear_on_submit=False):
                    to = st.text_area('받는 사람 이메일 주소 (여러 명 가능)',
                                      value=st.session_state.pending_email.get('to', ''), height=100,
                                      help='쉼표, 세미콜론 또는 줄바꿈으로 구분하세요. 최대 10개, 각각 개별 발송합니다.')
                    subject = st.text_input('제목', value=st.session_state.pending_email.get('subject', ''))
                    body = st.text_area('본문 (수정 가능)', value=st.session_state.pending_email.get('body', ''), height=220)
                    confirm = st.form_submit_button('✅ 입력한 모든 수신자에게 발송 확인', type='primary')
                if confirm:
                    st.session_state.pending_email = {'to': to, 'subject': subject, 'body': body}
                    try:
                        recipients = parse_recipients(to)
                        if not subject.strip() or not body.strip():
                            raise ValueError('제목과 본문을 입력해 주세요.')
                        with st.spinner(f'{len(recipients)}명에게 개별 이메일을 보내는 중...'):
                            results = send_emails(recipients, subject, body)
                        st.session_state.email_results = results
                        success = [x for x in results if x['status'] == 'success']
                        failed = [x for x in results if x['status'] != 'success']
                        if success:
                            st.success(f'Gmail 서버 접수: {len(success)}건 / {len(recipients)}건 (실제 배달은 수신 서버 상태에 따라 다를 수 있습니다)')
                        if failed:
                            st.error(f'발송 실패: {len(failed)}건. 아래 결과를 확인하고 실패 주소만 재시도하세요.')
                        else:
                            st.session_state.pending_email = None
                    except ValueError as exc:
                        st.error(str(exc))
                if st.button('초안 취소'):
                    st.session_state.pending_email = None
                    st.session_state.email_results = []
                    st.rerun()
        if st.session_state.email_results:
            st.markdown('**수신자별 전송 결과**')
            for item in st.session_state.email_results:
                if item['status'] == 'success':
                    st.caption(f"✓ {item['to']} · Gmail 접수")
                else:
                    st.warning(f"{item['to']} · {item['error']}")
