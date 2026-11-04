import os
import streamlit as st
from openai import OpenAI

# OpenAI 클라이언트 생성 (Streamlit Secrets에서 자동으로 API 키를 읽어옵니다)
client = OpenAI()

# 페이지 설정
st.set_page_config(page_title="음성 AI 서비스", page_icon="🤖", layout="wide")
st.title("음성 인식 AI 서비스")
st.write("음성 파일 업로드 또는 마이크 녹음으로 질문하시면 답변해 드립니다.")

# 역할 지정
sys_role = """
당신은 다양한 업무를 처리하는 AI 서비스입니다. 
개인 비서처럼 친절하게 응대합니다.
"""

# 상태 초기화
if "messages" not in st.session_state:
    st.session_state.messages = []

# 지시 영역
with st.form("task_form"):
    uploaded_file = st.file_uploader("음성 파일 업로드", type=["m4a", "mp3", "wav"])
    audio_value = st.audio_input("또는 마이크로 녹음하기")
    submit = st.form_submit_button("실행")

# 버튼을 눌렀을 때만 실행
if submit:
    # 1. 파일이나 녹음 둘 다 없으면 경고 후 중단
    if audio_value is None and uploaded_file is None:
        st.warning("음성을 녹음하거나 음성 파일을 업로드해주세요.")
        st.stop()

    # 2. 사용할 오디오 소스 결정 (업로드 파일 우선, 없으면 녹음 사용)
    if uploaded_file is not None:
        audio_source = uploaded_file
        file_name = uploaded_file.name
    else:
        audio_source = audio_value
        file_name = "audio.wav"

    # 3. 시스템 메시지 설정
    system_content = sys_role
    input_messages = [{"role": "system", "content": system_content}]

    # 4. STT: 음성 → 텍스트 변환 (Whisper API)
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

    # 변환된 사용자 텍스트 출력
    st.info(f"인식된 텍스트: {user_text}")

    # 사용자 메시지 추가
    input_messages.append({"role": "user", "content": user_text})

    # 5. LLM 호출 및 응답 받기
    with st.spinner("답변을 준비하고 있습니다..."):
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=input_messages
            )
            answer = response.choices[0].message.content

            # 응답 출력
            st.subheader("AI 답변")
            st.write(answer)
        except Exception as e:
            st.error(f"LLM 응답 생성 중 오류가 발생했습니다: {e}")
