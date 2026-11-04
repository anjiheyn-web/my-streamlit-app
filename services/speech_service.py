"""1일차 STT/TTS 함수의 Streamlit 버전."""
def transcribe_audio(client, model, audio_bytes):
    if not audio_bytes:
        return ''
    response = client.audio.transcriptions.create(model=model, file=('voice.wav', audio_bytes, 'audio/wav'))
    return response.text.strip()


def make_speech(client, model, text):
    if not text.strip():
        raise ValueError('음성으로 변환할 텍스트가 없습니다.')
    # Speech API 입력 길이 제한에 대비 (전체 텍스트는 화면에서 계속 제공)
    response = client.audio.speech.create(model=model, voice='alloy', input=text[:3500], response_format='mp3')
    return response.content
