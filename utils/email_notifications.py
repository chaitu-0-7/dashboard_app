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


def send_nifty50_update_email(to_email: str, result: dict, positions_in_removed: list = None):
    """
    Send NIFTY 50 constituents update email to admin
    
    Args:
        to_email: Admin email address
        result: Update result dict from Nifty50Manager
        positions_in_removed: List of positions in removed stocks
    """
    smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
    smtp_port = int(os.getenv('SMTP_PORT', 587))
    sender_email = os.getenv('SMTP_EMAIL')
    sender_password = os.getenv('SMTP_PASSWORD')

    if not sender_email or not sender_password:
        print("SMTP credentials not found. Skipping email.")
        return False

    # Build email content based on result
    status_emoji = "✅" if result['status'] == 'completed' else "❌"
    status_text = "Completed" if result['status'] == 'completed' else "Failed"
    
    subject = f"{status_emoji} NIFTY 50 List Update - {status_text}"
    
    # Build body (truncated for brevity in error case)
    body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6;">
        <h2 style="color: {'#10b981' if result['status'] == 'completed' else '#ef4444'};">
            {status_emoji} NIFTY 50 Update {status_text}
        </h2>
        <p><strong>Date:</strong> {result.get('update_date', 'N/A')}</p>
        <p><strong>Source:</strong> {result.get('source_used', 'N/A')}</p>
        <p>Added: {len(result.get('symbols_added', []))} symbols</p>
        <p>Removed: {len(result.get('symbols_removed', []))} symbols</p>
        <br>
        <p style="color: #6b7280; font-size: 0.9em;">
            Best regards,<br>
            Nifty Shop Admin
        </p>
    </body>
    </html>
    """

    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'html'))

    try:
        print(f"Sending email to {to_email}...")
        server = smtplib.SMTP(smtp_server, smtp_port, timeout=10)
        server.starttls(timeout=10)
        server.login(sender_email, sender_password, timeout=10)
        server.sendmail(sender_email, to_email, msg.as_string())
        server.quit()
        print(f"✅ NIFTY 50 update email sent to {to_email}")
        return True
    except smtplib.SMTPException as e:
        print(f"SMTP Error: {e}")
        return False
    except Exception as e:
        print(f"Failed to send NIFTY 50 update email: {e}")
        return False
