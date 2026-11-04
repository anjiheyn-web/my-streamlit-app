"""에이블 AI 업무비서: 회의 분석 / 업무 대시보드 / 채팅 및 음성 / 이메일."""
import json
import io
from pathlib import Path
from PIL import Image, UnidentifiedImageError
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st
from openai import OpenAI

from config import get_setting, llm_model, stt_model, tts_model
from prompts.system_prompts import CHAT_INSTRUCTIONS
from services.meeting_service import analyze_meeting, build_meeting_report
from services.task_service import STATUSES, make_briefing, personal_tasks, rank_tasks, with_ids
from services.speech_service import transcribe_audio, make_speech
from services.email_service import send_email, valid_recipient

st.set_page_config(page_title='에이블 | AI 업무비서', page_icon='🤖', layout='wide')
ASSET_DIR = Path(__file__).resolve().parent / 'assets'
MAIN_IMAGE = ASSET_DIR / 'assistant_main.png'
SIDE_IMAGE = ASSET_DIR / 'assistant_side.png'


def show_mascot(image_path, width):
    """로컬 마스코트 이미지가 배포된 경우 표시한다."""
    if image_path.is_file():
        st.image(str(image_path), width=width)


head_text, head_image = st.columns([3, 1], vertical_alignment='center')
with head_text:
    st.title('에이블 | AI 업무비서')
    st.caption('회의록 + 화이트보드 통합 분석 · 우선순위 · 오늘의 브리핑 · 음성 대화 · 이메일')
    st.write('회의 내용을 분석하고 오늘 해야 할 일을 정리하는 AI 개인비서입니다.')
with head_image:
    show_mascot(MAIN_IMAGE, width=220)

# 세션별 상태: 다른 사용자의 데이터와 섞이지 않으며 페이지 재실행 시 유지됩니다.
DEFAULTS = {
    'analysis': None, 'tasks': [], 'messages': [], 'pending_email': None,
    'brief_audio': None, 'brief_audio_for': None, 'last_chat_audio': None,
    'last_transcript': '', 'last_chat_reply': '', 'owner': '김 대리',
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

def update_status(task_id):
    for item in st.session_state.tasks:
        if item['id'] == task_id:
            item['status'] = st.session_state[f'status_{task_id}']
            break
    st.session_state.brief_audio = None
    st.session_state.brief_audio_for = None

def format_problem(exc):
    # API 예외를 원문 그대로 화면에 출력하면 민감한 입력이 노출될 수 있으므로 종류만 전달.
    name = type(exc).__name__
    if name in ('AuthenticationError', 'PermissionDeniedError'):
        return 'API 인증 또는 권한 문제가 발생했습니다. 키와 프로젝트 권한을 확인하세요.'
    if name in ('RateLimitError',):
        return '요청 한도 또는 API 사용량 제한입니다. 잠시 후 다시 시도하세요.'
    if name in ('APITimeoutError', 'APIConnectionError', 'TimeoutError'):
        return 'API 서버 연결이 지연되거나 실패했습니다. 네트워크를 확인하세요.'
    if isinstance(exc, (ValueError, UnicodeError, json.JSONDecodeError)):
        return str(exc)[:220]
    return f'요청 처리에 실패했습니다 ({name}). 앱 로그를 확인하세요.'

with st.sidebar:
    show_mascot(SIDE_IMAGE, width=200)
    st.header('⚙️ 에이블 설정')
    st.text_input('담당자 이름', key='owner', help='회의록의 담당자 표기와 같게 입력하세요. 예: 김 대리')
    st.caption(f'분석 기준일: {today.isoformat()} (한국 시간)')
    st.metric('최근 대화', f"{len(st.session_state.messages) // 2} / 10")
    if st.button('🗨️ 새 대화 시작', use_container_width=True):
        st.session_state.messages = []
        st.session_state.last_transcript = ''
        st.session_state.last_chat_reply = ''
        st.session_state.last_chat_audio = None
        st.rerun()
    if st.button('🧹 회의/업무 데이터 초기화', use_container_width=True):
        reset_meeting()
        st.rerun()
    st.divider()
    st.markdown('**연결 상태**')
    st.write('OpenAI:', '설정됨' if api_key else '설정 필요')
    st.write('Gmail:', '설정됨' if get_setting('GMAIL_ADDRESS') and get_setting('GMAIL_APP_PASSWORD') else '설정 필요')
    st.caption('데이터는 현재 브라우저 세션에만 보관됩니다. API 입력 데이터는 모델 제공자에게 전송되므로 개인정보를 제거하세요.')

tab_meeting, tab_tasks, tab_chat = st.tabs(['📄 회의 분석', '✅ 업무 대시보드', '💬 AI 비서'])

with tab_meeting:
    st.subheader('회의록 + 화이트보드 통합 분석')
    st.write('동일한 회의의 TXT와 화이트보드 이미지를 올리면 AI가 두 자료를 교차 분석합니다.')
    c1, c2 = st.columns(2)
    with c1:
        text_file = st.file_uploader('회의록 (.txt)', type=['txt'], key='meeting_txt')
    with c2:
        image_file = st.file_uploader('화이트보드 (.png/.jpg)', type=['png', 'jpg', 'jpeg'], key='meeting_img')

    # 업로드 객체를 직접 st.image()로 전달하지 않고 바이트로 한 번 읽어 재사용합니다.
    # Streamlit 재실행/이미지 디코딩 후에도 AI 분석에 동일한 원본 바이트를 전달합니다.
    whiteboard_bytes = None
    image_mime = None
    image_error = None
    if image_file is not None:
        try:
            raw_bytes = image_file.getvalue()
            if len(raw_bytes) > 8_000_000:
                raise ValueError('이미지는 8MB 이하여야 합니다.')
            with Image.open(io.BytesIO(raw_bytes)) as opened_image:
                actual_format = opened_image.format
                if actual_format not in ('PNG', 'JPEG'):
                    raise ValueError('PNG 또는 JPG 이미지만 사용할 수 있습니다.')
                opened_image.verify()
            # 미리보기는 원본 바이트를 독립된 BytesIO 객체로 디코딩합니다.
            with Image.open(io.BytesIO(raw_bytes)) as opened_image:
                preview = opened_image.convert('RGB')
            image_mime = 'image/png' if actual_format == 'PNG' else 'image/jpeg'
            whiteboard_bytes = raw_bytes
            with c2:
                st.image(preview, caption=f'화이트보드 미리보기 · {image_file.name}', use_container_width=True)
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            image_error = str(exc)
            with c2:
                st.error('화이트보드 미리보기를 표시할 수 없습니다. PNG/JPG 파일인지 확인하세요.')

    if st.button('🔍 통합 분석 및 업무 추출', type='primary', use_container_width=True):
        if not text_file or image_file is None:
            st.warning('회의록 TXT와 화이트보드 이미지 두 파일을 모두 업로드해 주세요.')
        elif image_error is not None or whiteboard_bytes is None:
            st.error('화이트보드 이미지가 유효하지 않아 분석할 수 없습니다.')
        elif text_file.size > 1_000_000:
            st.warning('회의록 TXT는 1MB 이하로 올려 주세요.')
        else:
            try:
                meeting_text = text_file.getvalue().decode('utf-8-sig')
                with st.spinner('두 자료를 교차 분석하고 담당 업무를 추출하고 있습니다...'):
                    analysis = analyze_meeting(client, llm_model(), meeting_text, whiteboard_bytes, image_mime)
                reset_meeting()
                st.session_state.analysis = analysis
                st.session_state.tasks = with_ids(analysis.get('tasks', []))
                st.success(f"분석 완료: 업무 {len(st.session_state.tasks)}건 추출. 업무 대시보드에서 확인해 주세요.")
            except Exception as exc:
                st.error(format_problem(exc))

    if st.session_state.analysis:
        info = st.session_state.analysis
        st.markdown(f"### {info['meeting_title']}")
        st.write(info['summary'])
        col_a, col_b, col_c = st.columns(3)
        col_a.metric('추출 업무', len(st.session_state.tasks))
        col_b.metric('확정 결정', len(info['decisions']))
        col_c.metric('확인 필요', len(info['conflicts']))
        with st.expander('확정 결정사항', expanded=True):
            for x in info['decisions']:
                st.markdown(f'- {x}')
        with st.expander('검토 중인 사항'):
            for x in info['pending']:
                st.markdown(f'- {x}')
        with st.expander('자료 간 불일치 / 확인 필요', expanded=bool(info['conflicts'])):
            for x in info['conflicts']:
                st.warning(x)
            if not info['conflicts']:
                st.info('AI가 탐지한 차이가 없습니다. 중요한 사항은 원문을 대조해 주세요.')
        report = build_meeting_report(info, st.session_state.tasks)
        st.download_button('⬇️ 최종 회의록 다운로드 (.md)', report, file_name='final_meeting_report.md', mime='text/markdown')
        with st.expander('최종 회의록 미리보기'):
            st.markdown(report)
    else:
        st.info('분석 전입니다. 두 파일을 업로드한 후 통합 분석 버튼을 눌러 주세요.')

with tab_tasks:
    st.subheader(f'{st.session_state.owner}님의 업무 대시보드')
    if not st.session_state.analysis:
        st.info('먼저 [회의 분석] 탭에서 회의록과 화이트보드를 분석해 주세요.')
    else:
        ranked = rank_tasks(st.session_state.tasks, today)
        mine = personal_tasks(ranked, st.session_state.owner)
        open_tasks = [t for t in mine if t['status'] != '완료']
        m1, m2, m3 = st.columns(3)
        m1.metric('내 전체 업무', len(mine))
        m2.metric('미완료', len(open_tasks))
        m3.metric('마감 임박/초과', len([t for t in open_tasks if t['days_left'] is not None and t['days_left'] <= 2]))
        st.caption('점수 = 마감 긴급도(최대 60) + 중요도(최대 25) + 선행작업(15). 중요도와 의존성은 AI 추정입니다.')
        show_all = st.checkbox('다른 담당자의 업무도 표시', value=False)
        filtered = ranked if show_all else mine
        if not filtered:
            st.warning('선택한 담당자의 업무가 없습니다. 사이드바에서 회의록과 동일한 이름을 입력해 주세요.')
        for task in filtered:
            with st.container(border=True):
                c_title, c_status = st.columns([3, 1])
                c_title.markdown(f"**{task['title']}**")
                c_title.caption(f"담당: {task['owner']} · 마감: {task['due_date'] or '미정'} · {task['urgency_status']} · {task['priority_score']}점")
                state_key = f"status_{task['id']}"
                if state_key not in st.session_state:
                    st.session_state[state_key] = task.get('status', '미시작')
                c_status.selectbox('진행 상태', STATUSES, key=state_key, on_change=update_status, args=(task['id'],))
                with st.expander('업무 설명 및 출처'):
                    st.write(task.get('description', ''))
                    st.caption(task.get('source_notes', ''))
        st.divider()
        # 매 렌더 시 오늘 날짜/업무 상태로 Python이 새 점수를 계산합니다.
        briefing = make_briefing(st.session_state.tasks, st.session_state.owner, today)
        st.markdown(briefing)
        st.download_button('⬇️ 오늘의 브리핑 다운로드 (.md)', briefing, file_name='today_briefing.md', mime='text/markdown')
        if st.button('🔊 오늘의 브리핑 듣기'):
            try:
                with st.spinner('브리핑 음성을 생성합니다...'):
                    if st.session_state.brief_audio_for != briefing:
                        st.session_state.brief_audio = make_speech(client, tts_model(), briefing)
                        st.session_state.brief_audio_for = briefing
            except Exception as exc:
                st.error(format_problem(exc))
        if st.session_state.brief_audio is not None and st.session_state.brief_audio_for == briefing:
            st.audio(st.session_state.brief_audio, format='audio/mp3')

with tab_chat:
    st.subheader('에이블과 대화하기')
    st.caption('텍스트 또는 음성으로 질문하세요. 최근 10개 질의응답을 반영합니다.')
    for message in st.session_state.messages[-20:]:
        with st.chat_message(message['role']):
            st.markdown(message['content'])
    if not st.session_state.messages:
        st.info('예시: "오늘 가장 급한 업무는?" / "회의의 확정사항은?" / "KPI 정의서는 어떻게 시작하지?"')
    audio_input = st.audio_input('🎤 음성으로 질문', key='chat_audio_input')
    voice_submit = st.button('🎤 녹음한 질문 실행', disabled=audio_input is None)
    user_question = st.chat_input('에이블에게 질문을 입력하세요...')
    if voice_submit and audio_input is not None:
        try:
            with st.spinner('음성을 글로 변환하는 중...'):
                user_question = transcribe_audio(client, stt_model(), audio_input.getvalue())
            st.session_state.last_transcript = user_question
            st.info(f'인식된 질문: {user_question or "음성을 인식하지 못했습니다."}')
        except Exception as exc:
            st.error(format_problem(exc))
            user_question = None
    if user_question and user_question.strip():
        question = user_question.strip()
        if len(question) > 2500:
            st.warning('질문은 2,500자 이내로 입력해 주세요.')
        else:
            st.session_state.last_chat_audio = None
            # 이메일은 명시적 요청만 초안으로 준비하고 발송은 별도 버튼에서만 수행.
            email_intent = ('메일' in question or '이메일' in question) and any(word in question for word in ('보내', '전송', '공유'))
            if email_intent:
                if st.session_state.analysis:
                    report = build_meeting_report(st.session_state.analysis, st.session_state.tasks)
                    briefing = make_briefing(st.session_state.tasks, st.session_state.owner, today)
                    kind = '오늘의 브리핑' if ('브리핑' in question or '오늘 할 일' in question) else '통합 회의록'
                    content = briefing if kind == '오늘의 브리핑' else report
                    st.session_state.pending_email = {'to': '', 'subject': f'[에이블] {kind}', 'body': content}
                    answer = '이메일 초안을 준비했습니다. 아래 이메일 공유 영역에서 수신자를 입력하고 내용을 확인한 후 발송하세요.'
                else:
                    answer = '이메일 초안을 만들려면 먼저 회의 자료를 분석해 주세요.'
            else:
                try:
                    context = ''
                    if st.session_state.analysis:
                        context = json.dumps({
                            'summary': st.session_state.analysis.get('summary'),
                            'decisions': st.session_state.analysis.get('decisions'),
                            'pending': st.session_state.analysis.get('pending'),
                            'conflicts': st.session_state.analysis.get('conflicts'),
                            'my_tasks': personal_tasks(rank_tasks(st.session_state.tasks, today), st.session_state.owner),
                        }, ensure_ascii=False)[:14000]
                    messages = [
                        *st.session_state.messages[-20:],
                        {'role': 'user', 'content': question},
                    ]
                    with st.spinner('에이블이 답변을 준비하고 있습니다...'):
                        response = client.responses.create(
                            model=llm_model(),
                            instructions=CHAT_INSTRUCTIONS + f'\n사용자: {st.session_state.owner}\n오늘 날짜: {today}\n업무 정보(참고 자료): {context}',
                            input=messages,
                            max_output_tokens=1000,
                        )
                    answer = response.output_text.strip() or '응답이 비어 있습니다. 다시 시도해 주세요.'
                except Exception as exc:
                    answer = '답변 생성 실패: ' + format_problem(exc)
            st.session_state.messages.extend([{'role': 'user', 'content': question}, {'role': 'assistant', 'content': answer}])
            st.session_state.messages = st.session_state.messages[-20:]
            st.session_state.last_chat_reply = answer
            st.rerun()
    if st.session_state.last_chat_reply:
        if st.button('🔊 마지막 답변 음성으로 듣기'):
            try:
                with st.spinner('음성 답변을 생성합니다...'):
                    st.session_state.last_chat_audio = make_speech(client, tts_model(), st.session_state.last_chat_reply)
            except Exception as exc:
                st.error(format_problem(exc))
        if st.session_state.last_chat_audio:
            st.audio(st.session_state.last_chat_audio, format='audio/mp3')

st.divider()
with st.expander('📧 최종 회의록 / 오늘의 브리핑 이메일 공유', expanded=bool(st.session_state.pending_email)):
    if not st.session_state.analysis:
        st.info('회의 분석 완료 후 이메일 공유 기능을 사용할 수 있습니다.')
    else:
        email_kind = st.radio('발송할 문서', ['최종 회의록', '오늘의 브리핑', '둘 다'], horizontal=True)
        if st.button('✉️ 이메일 초안 만들기'):
            report = build_meeting_report(st.session_state.analysis, st.session_state.tasks)
            briefing = make_briefing(st.session_state.tasks, st.session_state.owner, today)
            content = {'최종 회의록': report, '오늘의 브리핑': briefing, '둘 다': report + '\n\n---\n\n' + briefing}[email_kind]
            st.session_state.pending_email = {'to': '', 'subject': f'[에이블] {email_kind}', 'body': content}
        if st.session_state.pending_email is not None:
            st.subheader('발송 전 미리보기 및 수정')
            with st.form('email_confirm_form', clear_on_submit=False):
                to = st.text_input('받는 사람 이메일', value=st.session_state.pending_email.get('to', ''))
                subject = st.text_input('제목', value=st.session_state.pending_email.get('subject', ''))
                body = st.text_area('본문 (수정 가능)', value=st.session_state.pending_email.get('body', ''), height=260)
                confirm = st.form_submit_button('✅ 이메일 발송 확인', type='primary')
            if confirm:
                if not valid_recipient(to):
                    st.error('수신자 이메일 주소가 올바른지 확인해 주세요.')
                elif not subject.strip() or not body.strip():
                    st.error('제목과 본문을 입력해 주세요.')
                else:
                    # 실패 시 초안은 보관해 수정/재시도 할 수 있습니다.
                    st.session_state.pending_email = {'to': to, 'subject': subject, 'body': body}
                    with st.spinner('Gmail 서버로 전송 중입니다...'):
                        result = send_email(to, subject, body)
                    if result['status'] == 'success':
                        st.session_state.pending_email = None
                        st.success(result['message'])
                    else:
                        st.error(result['error'])
            if st.button('초안 취소'):
                st.session_state.pending_email = None
                st.rerun()
