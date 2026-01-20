import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os

def send_approval_email(user_email, user_name):
    smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
    smtp_port = int(os.getenv('SMTP_PORT', 587))
    sender_email = os.getenv('SMTP_EMAIL')
    sender_password = os.getenv('SMTP_PASSWORD')

    if not sender_email or not sender_password:
        print("SMTP credentials not found. Skipping email.")
        return False

    subject = "Account Approved - Nifty Shop"
    body = f"""
    <html>
    <body>
        <h2>Welcome to Nifty Shop, {user_name}!</h2>
        <p>Your account has been approved by the administrator.</p>
        <p>You can now log in using your Google account.</p>
        <br>
        <a href="{os.getenv('APP_URL', 'http://localhost:8080')}/login" 
           style="background-color: #4CAF50; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">
           Login Now
        </a>
    </body>
    </html>
    """

    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = user_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'html'))

    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, user_email, msg.as_string())
        server.quit()
        print(f"Approval email sent to {user_email}")
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False

def send_removal_email(user_email, user_name):
    smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
    smtp_port = int(os.getenv('SMTP_PORT', 587))
    sender_email = os.getenv('SMTP_EMAIL')
    sender_password = os.getenv('SMTP_PASSWORD')

    if not sender_email or not sender_password:
        return False

    subject = "Account Removed - Nifty Shop"
    body = f"""
    <html>
    <body>
        <h2>Account Removed</h2>
        <p>Dear {user_name},</p>
        <p>Your access to <b>Nifty Shop</b> has been revoked by the administrator.</p>
        <p>If you believe this is a mistake, please contact the support team.</p>
        <br>
        <p>Best regards,<br>Nifty Shop Admin</p>
    </body>
    </html>
    """

    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = user_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'html'))

    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, user_email, msg.as_string())
        server.quit()
        print(f"Removal email sent to {user_email}")
        return True
    except Exception as e:
        print(f"Failed to send removal email: {e}")
        return False

def send_token_expiry_alert(user_email, user_name):
    smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
    smtp_port = int(os.getenv('SMTP_PORT', 587))
    sender_email = os.getenv('SMTP_EMAIL')
    sender_password = os.getenv('SMTP_PASSWORD')

    if not sender_email or not sender_password:
        return False

    subject = "Action Required: Refresh Trading Token - Nifty Shop"
    body = f"""
    <html>
    <body>
        <h2>Action Required</h2>
        <p>Dear {user_name},</p>
        <p>Your trading account token (Fyers) has expired and could not be auto-refreshed.</p>
        <p>This means your automated strategy <b>will not run</b> until you intervene.</p>
        <br>
        <p>Please login to Nifty Shop immediately to generate a new token:</p>
        <a href="{os.getenv('APP_URL', 'http://localhost:8080')}/login" 
           style="background-color: #ef4444; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">
           Login to Fix
        </a>
        <br><br>
        <p>Best regards,<br>Nifty Shop Admin</p>
    </body>
    </html>
    """

    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = user_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'html'))

    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, user_email, msg.as_string())
        server.quit()
        print(f"Token Expiry Alert sent to {user_email}")
        return True
    except Exception as e:
        print(f"Failed to send alert email: {e}")
        return False
