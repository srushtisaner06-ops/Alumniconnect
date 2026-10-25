
from app import config, notifier

# Always send the test to your own inbox.
recipient = config.SMTP_USER

if not recipient:
    raise RuntimeError("SMTP_USER is missing from .env")

if not notifier.email_configured():
    raise RuntimeError("SMTP is not configured")

print("SMTP host:", config.SMTP_HOST)
print("SMTP port:", config.SMTP_PORT)
print("Sending one test email to:", recipient)

notifier.send_email(
    to=recipient,
    subject="AlumniConnect - SMTP Test",
    body=(
        "Hello!\n\n"
        "This is a test email from AlumniConnect.\n"
        "It verifies that the Gmail SMTP connection is working.\n\n"
        "No alumni campaign has been started.\n"
    ),
)

print("Email accepted by the SMTP server.")
