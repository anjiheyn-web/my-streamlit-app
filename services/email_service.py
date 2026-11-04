"""메일은 미리보기 후 사용자가 확인 버튼을 눌렀을 때만 발송."""
import re
import smtplib
import ssl
from email.message import EmailMessage

from config import get_setting


def valid_recipient(address):
    return bool(re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', (address or '').strip()))


def send_email(to, subject, body):
    to = to.strip()
    if not valid_recipient(to):
        return {'status': 'failed', 'error': '수신자 주소 형식을 확인해 주세요.'}
    sender = get_setting('GMAIL_ADDRESS')
    password = (get_setting('GMAIL_APP_PASSWORD') or '').replace(' ', '')
    if not sender or not password:
        return {'status': 'failed', 'error': 'Streamlit Secrets의 GMAIL_ADDRESS / GMAIL_APP_PASSWORD 설정이 없습니다.'}
    message = EmailMessage()
    message['From'] = sender
    message['To'] = to
    message['Subject'] = subject
    message.set_content(body)
    try:
        with smtplib.SMTP('smtp.gmail.com', 587, timeout=25) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
            smtp.login(sender, password)
            smtp.send_message(message)
        return {'status': 'success', 'message': 'Gmail 서버가 메일을 접수했습니다.'}
    except smtplib.SMTPRecipientsRefused as exc:
        codes = [str(info[0]) for info in exc.recipients.values()]
        return {'status': 'failed', 'error': '수신자가 거부되었습니다. 주소와 Gmail 발송 정책을 확인해 주세요. SMTP 코드: ' + ', '.join(codes)}
    except smtplib.SMTPAuthenticationError:
        return {'status': 'failed', 'error': 'Gmail 인증 실패: Gmail 앱 비밀번호와 계정 설정을 확인해 주세요.'}
    except (smtplib.SMTPException, OSError) as exc:
        return {'status': 'failed', 'error': f'SMTP 연결 또는 전송 실패 ({type(exc).__name__}). Streamlit 로그에서 원인을 확인해 주세요.'}
