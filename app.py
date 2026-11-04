import os
import streamlit as st
from openai import OpenAI

# OpenAI 클라이언트 생성
client = OpenAI()

# 페이지 설정
st.set_page_config(page_title="음성 AI 서비스", page_icon="🤖", layout="wide")
st.title("🤖 음성 인식 AI 서비스")

# 역할 지정
sys_role = """
당신은 다양한 업무를 처리하는 AI 서비스입니다. 
개인 비서처럼 친절하게 응대합니다.
"""

# 세션 상태 초기화 (대화 기록 저장용)
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "system", "content": sys_role}]

# --- [상단 고정 영역] 입력 및 녹음부 ---
st.write("음성 파일 업로드 또는 마이크로 녹음하여 질문하시면 답변해 드립니다.")

uploaded_file = st.file_uploader("음성 파일 업로드", type=["m4a", "mp3", "wav"])
audio_value = st.audio_input("또는 마이크로 녹음하기")

# 실행 버튼
submit_btn = st.button("실행")

st.write("---")
st.subheader("💬 대화 내용")

# --- [스크롤 영역] 대화 기록 출력용 컨테이너 (높이 지정으로 스크롤바 생성) ---
chat_container = st.container(height=450)

with chat_container:
    for message in st.session_state.messages:
        if message["role"] == "user":
            with st.chat_message("user"):
                st.write(message["content"])
        elif message["role"] == "assistant":
            with st.chat_message("assistant"):
                st.write(message["content"])

# --- 실행 로직 처리 ---
if submit_btn:
    # 파일이나 녹음 둘 다 없으면 경고 후 중단
    if audio_value is None and uploaded_file is None:
        st.warning("음성을 녹음하거나 음성 파일을 업로드해주세요.")
        st.stop()

    # 사용할 오디오 소스 결정 (업로드 파일 우선, 없으면 녹음 사용)
    if uploaded_file is not None:
        audio_source = uploaded_file
        file_name = uploaded_file.name
    else:
        audio_source = audio_value
        file_name = "audio.wav"

    # STT: 음성 → 텍스트 변환 (Whisper API)
    with st.spinner("음성을 텍스트로 변환하고 있습니다..."):
        try:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=(file_name, audio_source)
            )
            user_text = transcript.text
        except Exception as e:
            st.error(f"음성 변환 중 오류가 발생했습니다: {e}")
            st.stop()

    # 사용자 메시지 세션에 추가
    st.session_state.messages.append({"role": "user", "content": user_text})

    # LLM 호출 및 응답 받기
    with st.spinner("답변을 준비하고 있습니다..."):
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=st.session_state.messages
            )
            answer = response.choices[0].message.content

            # 어시스턴트 메시지 세션에 추가
            st.session_state.messages.append({"role": "assistant", "content": answer})
                
            # 화면을 즉시 갱신하여 상단 녹음기 위치는 고정된 채 대화창만 업데이트
            st.rerun()
            
        except Exception as e:
            st.error(f"LLM 응답 생성 중 오류가 발생했습니다: {e}")
