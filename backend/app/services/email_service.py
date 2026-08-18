"""
FindIt Campus — Email Notification Service
Sends email alerts for match found, claim approved, welcome, and verification events.
Uses Flask-Mail with Gmail SMTP (finditcampus@gmail.com).
"""

import threading
from flask import current_app
from flask_mail import Message
from app import mail


def _send_email(subject, recipients, body_html, body_text=None):
    """Send an email with HTML body. Silently logs on failure."""
    try:
        msg = Message(
            subject=subject,
            recipients=recipients,
            html=body_html,
            body=body_text or ''
        )
        mail.send(msg)
        return True
    except Exception as e:
        print(f"[EmailService] Failed to send email to {recipients}: {e}")
        return False


def _send_email_async_worker(app, subject, recipients, body_html, body_text=None):
    """Worker function executed inside background thread with app context."""
    with app.app_context():
        _send_email(subject, recipients, body_html, body_text)


def send_email_async(app, subject, recipients, body_html, body_text=None):
    """Launch email sending in a non-blocking background thread with app context."""
    thread = threading.Thread(
        target=_send_email_async_worker,
        args=(app, subject, recipients, body_html, body_text),
        daemon=True
    )
    thread.start()
    return thread


def send_verification_email(student, token, app_url="http://localhost:5000"):
    """
    Send an email verification link to the student's email address from finditcampus@gmail.com.
    """
    if not student or not student.college_email:
        return False

    verify_url = f"{app_url}/verify-email?token={token}"
    subject = "✉️ Verify Your Email Address — FindIt Campus"

    html = f"""
    <div style="font-family:Inter,Arial,sans-serif;max-width:600px;margin:0 auto;background:#fff;border:1px solid #e2e8f0;border-radius:12px;overflow:hidden;">
      <div style="background:linear-gradient(135deg,#2563eb,#7c3aed);padding:32px 24px;text-align:center;">
        <h1 style="color:#fff;font-size:22px;margin:0;">✉️ Verify Your Email Address</h1>
        <p style="color:#bfdbfe;font-size:13px;margin:8px 0 0 0;">FindIt Campus — Smart Lost &amp; Found</p>
      </div>
      <div style="padding:28px 24px;">
        <p style="font-size:15px;color:#1e293b;">Hi <strong>{student.student_name}</strong>,</p>
        <p style="color:#475569;font-size:14px;line-height:1.6;">
          Please verify your email address (<strong>{student.college_email}</strong>) to activate mandatory instant email notifications when items matching your reports are found.
        </p>

        <div style="text-align:center;margin:32px 0;">
          <a href="{verify_url}" style="background:#2563eb;color:#fff;text-decoration:none;padding:14px 32px;border-radius:10px;font-weight:700;font-size:15px;display:inline-block;box-shadow:0 4px 12px rgba(37,99,235,0.3);">
            ✅ Verify My Email Now
          </a>
        </div>

        <p style="color:#94a3b8;font-size:12px;text-align:center;">
          Or copy and paste this URL into your browser:<br>
          <a href="{verify_url}" style="color:#2563eb;word-break:break-all;">{verify_url}</a>
        </p>
      </div>
      <div style="background:#f8fafc;padding:16px 24px;text-align:center;border-top:1px solid #f1f5f9;">
        <p style="color:#94a3b8;font-size:11px;margin:0;">Sent by FindIt Campus (finditcampus@gmail.com) · GIST</p>
      </div>
    </div>
    """
    try:
        app = current_app._get_current_object()
        send_email_async(app, subject, [student.college_email], html)
        return True
    except Exception:
        return _send_email(subject, [student.college_email], html)


def send_match_found_email(student, lost_item, found_item, match_score, recipient_type='lost'):
    """
    Notify a student that a potential match was found for an item.
    recipient_type: 'lost' for item owner, 'found' for item finder.
    """
    if not student or not student.college_email:
        return False

    score_pct = round(match_score * 100 if match_score <= 1 else match_score, 1)

    if recipient_type == 'lost':
        subject = f"🎯 Potential Match Found — {lost_item.item_name}"
        intro_text = "Great news! Our AI engine found a potential match for your lost item."
        primary_box_title = "Your Lost Item"
        primary_name = lost_item.item_name
        primary_sub = f"{lost_item.category} · {lost_item.color} · {lost_item.location}"

        secondary_box_title = "Matched Found Item"
        secondary_name = found_item.item_name
        secondary_sub = f"{found_item.category} · {found_item.color} · {found_item.location}"
        action_text = "Log in to your dashboard to review this match and verify your claim."
    else:
        subject = f"🎯 Item Match Alert — Found Item: {found_item.item_name}"
        intro_text = "A lost item report matches the item you found and reported on FindIt Campus!"
        primary_box_title = "Your Reported Found Item"
        primary_name = found_item.item_name
        primary_sub = f"{found_item.category} · {found_item.color} · {found_item.location}"

        secondary_box_title = "Matched Lost Item Report"
        secondary_name = lost_item.item_name
        secondary_sub = f"{lost_item.category} · {lost_item.color} · {lost_item.location}"
        action_text = "Log in to view match alerts and coordinate with the item owner."

    html = f"""
    <div style="font-family:Inter,Arial,sans-serif;max-width:600px;margin:0 auto;background:#fff;border:1px solid #e2e8f0;border-radius:12px;overflow:hidden;">
      <div style="background:linear-gradient(135deg,#2563eb,#4f46e5);padding:32px 24px;text-align:center;">
        <h1 style="color:#fff;font-size:22px;margin:0;">🎯 Potential Match Alert!</h1>
        <p style="color:#bfdbfe;font-size:13px;margin:8px 0 0 0;">FindIt Campus — Smart Lost &amp; Found</p>
      </div>
      <div style="padding:28px 24px;">
        <p style="font-size:15px;color:#1e293b;">Hi <strong>{student.student_name}</strong>,</p>
        <p style="color:#475569;font-size:14px;">{intro_text}</p>
        
        <div style="background:#f0f9ff;border:1px solid #bae6fd;border-radius:8px;padding:16px;margin:20px 0;">
          <p style="margin:0 0 8px 0;font-size:13px;color:#0369a1;font-weight:700;text-transform:uppercase;letter-spacing:.05em;">{primary_box_title}</p>
          <p style="margin:0;font-size:18px;font-weight:700;color:#0c4a6e;">{primary_name}</p>
          <p style="margin:4px 0 0 0;font-size:12px;color:#475569;">{primary_sub}</p>
        </div>

        <div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;padding:16px;margin:20px 0;">
          <p style="margin:0 0 8px 0;font-size:13px;color:#15803d;font-weight:700;text-transform:uppercase;letter-spacing:.05em;">{secondary_box_title}</p>
          <p style="margin:0;font-size:18px;font-weight:700;color:#14532d;">{secondary_name}</p>
          <p style="margin:4px 0 0 0;font-size:12px;color:#475569;">{secondary_sub}</p>
        </div>

        <div style="text-align:center;background:#fefce8;border:1px solid #fde68a;border-radius:8px;padding:16px;margin:20px 0;">
          <p style="margin:0;font-size:28px;font-weight:800;color:#92400e;">Match Score: {score_pct}%</p>
          <p style="margin:4px 0 0 0;font-size:12px;color:#78350f;">AI Confidence Score</p>
        </div>

        <p style="color:#475569;font-size:14px;">{action_text}</p>
        <div style="text-align:center;margin-top:24px;">
          <a href="http://localhost:5000/notifications" style="background:#2563eb;color:#fff;text-decoration:none;padding:12px 28px;border-radius:8px;font-weight:700;font-size:14px;">View Match Alerts</a>
        </div>
      </div>
      <div style="background:#f8fafc;padding:16px 24px;text-align:center;">
        <p style="color:#94a3b8;font-size:11px;margin:0;">FindIt Campus · Geethanjali Institute of Science &amp; Technology</p>
      </div>
    </div>
    """
    try:
        app = current_app._get_current_object()
        send_email_async(app, subject, [student.college_email], html)
        return True
    except Exception:
        return _send_email(subject, [student.college_email], html)


def send_claim_approved_email(student, finder_details):
    """
    Notify a student their ownership claim was approved.
    """
    if not student or not student.college_email:
        return False

    subject = "✅ Claim Approved — Collect Your Item!"

    html = f"""
    <div style="font-family:Inter,Arial,sans-serif;max-width:600px;margin:0 auto;background:#fff;border:1px solid #e2e8f0;border-radius:12px;overflow:hidden;">
      <div style="background:linear-gradient(135deg,#059669,#0d9488);padding:32px 24px;text-align:center;">
        <h1 style="color:#fff;font-size:22px;margin:0;">✅ Claim Approved!</h1>
        <p style="color:#a7f3d0;font-size:13px;margin:8px 0 0 0;">FindIt Campus — Smart Lost &amp; Found</p>
      </div>
      <div style="padding:28px 24px;">
        <p style="font-size:15px;color:#1e293b;">Hi <strong>{student.student_name}</strong>,</p>
        <p style="color:#475569;font-size:14px;">Your ownership claim has been verified and approved! Here are the finder's details so you can collect your item.</p>
        
        <div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;padding:16px;margin:20px 0;">
          <p style="margin:0 0 12px 0;font-size:13px;color:#15803d;font-weight:700;text-transform:uppercase;">Finder Details</p>
          <table style="width:100%;font-size:13px;color:#1e293b;border-collapse:collapse;">
            <tr><td style="padding:4px 0;color:#64748b;">Name</td><td style="font-weight:600;">{finder_details.get('student_name','N/A')}</td></tr>
            <tr><td style="padding:4px 0;color:#64748b;">Roll No</td><td style="font-weight:600;font-family:monospace;">{finder_details.get('roll_number','N/A')}</td></tr>
            <tr><td style="padding:4px 0;color:#64748b;">Department</td><td style="font-weight:600;">{finder_details.get('department','N/A')}</td></tr>
            <tr><td style="padding:4px 0;color:#64748b;">Email</td><td><a href="mailto:{finder_details.get('college_email','')}" style="color:#2563eb;">{finder_details.get('college_email','N/A')}</a></td></tr>
          </table>
        </div>

        <p style="color:#475569;font-size:13px;">Please contact the finder directly to arrange collection. Congratulations on recovering your item! 🎉</p>
      </div>
      <div style="background:#f8fafc;padding:16px 24px;text-align:center;">
        <p style="color:#94a3b8;font-size:11px;margin:0;">FindIt Campus · Geethanjali Institute of Science &amp; Technology</p>
      </div>
    </div>
    """
    try:
        app = current_app._get_current_object()
        send_email_async(app, subject, [student.college_email], html)
        return True
    except Exception:
        return _send_email(subject, [student.college_email], html)


def send_welcome_email(student):
    """
    Send a welcome email to a student when they first log in.
    """
    if not student or not student.college_email:
        return False

    subject = "👋 Welcome to FindIt Campus!"

    html = f"""
    <div style="font-family:Inter,Arial,sans-serif;max-width:600px;margin:0 auto;background:#fff;border:1px solid #e2e8f0;border-radius:12px;overflow:hidden;">
      <div style="background:linear-gradient(135deg,#2563eb,#7c3aed);padding:32px 24px;text-align:center;">
        <h1 style="color:#fff;font-size:22px;margin:0;">👋 Welcome to FindIt Campus!</h1>
        <p style="color:#bfdbfe;font-size:13px;margin:8px 0 0 0;">Smart Lost &amp; Found · GIST</p>
      </div>
      <div style="padding:28px 24px;">
        <p style="font-size:15px;color:#1e293b;">Hi <strong>{student.student_name}</strong>,</p>
        <p style="color:#475569;font-size:14px;">Welcome to FindIt Campus! You can now report lost items, browse found items, and get AI-powered match notifications.</p>
        
        <div style="background:#eff6ff;border-radius:8px;padding:16px;margin:20px 0;">
          <p style="margin:0 0 8px 0;font-weight:700;color:#1e40af;font-size:13px;">Your Account Details</p>
          <p style="margin:0;font-size:13px;color:#1e293b;">🎓 Roll Number: <strong>{student.roll_number}</strong></p>
          <p style="margin:4px 0 0 0;font-size:13px;color:#1e293b;">📧 Email: <strong>{student.college_email}</strong></p>
          <p style="margin:4px 0 0 0;font-size:13px;color:#1e293b;">🏛️ Department: <strong>{student.department}</strong></p>
        </div>

        <div style="text-align:center;margin-top:24px;">
          <a href="http://localhost:5000/dashboard" style="background:#2563eb;color:#fff;text-decoration:none;padding:12px 28px;border-radius:8px;font-weight:700;font-size:14px;">Go to Dashboard</a>
        </div>
      </div>
      <div style="background:#f8fafc;padding:16px 24px;text-align:center;">
        <p style="color:#94a3b8;font-size:11px;margin:0;">FindIt Campus · Geethanjali Institute of Science &amp; Technology</p>
      </div>
    </div>
    """
    try:
        app = current_app._get_current_object()
        send_email_async(app, subject, [student.college_email], html)
        return True
    except Exception:
        return _send_email(subject, [student.college_email], html)
