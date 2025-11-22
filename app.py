# Email verification fixed - Flask-Mail 0.9.1 syntax
import os
import uuid
from datetime import date, datetime, timedelta
from math import ceil
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, make_response
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_migrate import Migrate
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from sqlalchemy import or_
from dotenv import load_dotenv
from functools import wraps


from models import db, User, Property, Booking, Billing, Message, Policy, HelpSupport, PropertyImage, Review

# Load environment variables
load_dotenv()

# Flask setup
app = Flask(__name__)

# ========== PRODUCTION SECURITY CONFIGURATION ==========
app.secret_key = os.environ.get('SECRET_KEY')
if not app.secret_key:
    if os.environ.get('FLASK_ENV') == 'development':
        app.secret_key = 'dev-secret-key-change-in-production'
        print("⚠️  Using development secret key - CHANGE FOR PRODUCTION")
    else:
        raise ValueError("SECRET_KEY environment variable is required for production")

app.config['SECURITY_PASSWORD_SALT'] = os.environ.get('SECURITY_PASSWORD_SALT', app.secret_key + '-salt')
# Database setup with PostgreSQL support for Render
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
database_url = os.environ.get('DATABASE_URL')

if not database_url:
    # FIXED: Use absolute path with proper Windows formatting
    db_path = os.path.join(BASE_DIR, 'boardify.db')
    database_url = f"sqlite:///{db_path}"
    print(f"📊 Using SQLite database at: {db_path}")  # Optional: see where it's created

# Fix PostgreSQL URL for Render (postgres:// to postgresql://)
if database_url and database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 300,
}

# File upload configuration
app.config['MAX_IMAGE_COUNT'] = 10
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5MB
app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'static', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}




# Fix for URL generation in Render
if os.environ.get('RENDER'):
    # Get the Render external URL
    render_external_url = os.environ.get('RENDER_EXTERNAL_URL')
    if render_external_url:
        app.config['SERVER_NAME'] = render_external_url.replace('https://', '')
    else:
        # Fallback - Render provides this automatically
        app.config['PREFERRED_URL_SCHEME'] = 'https'
# Production settings for Render
if os.environ.get('RENDER'):
    app.config['DEBUG'] = False
    app.config['TESTING'] = False
    app.config['SESSION_COOKIE_SECURE'] = True
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['REMEMBER_COOKIE_SECURE'] = True
    app.config['REMEMBER_COOKIE_HTTPONLY'] = True
    app.config['PREFERRED_URL_SCHEME'] = 'https'

# Enhanced email availability check
EMAIL_ENABLED = bool(os.environ.get('RESEND_API_KEY'))



# Initialize extensions

ts = URLSafeTimedSerializer(app.config['SECRET_KEY'])

# Import models AFTER app configuration
try:
    from models import db, User, Property, Booking, Billing, Message, Policy, HelpSupport, PropertyImage, Review
except ImportError as e:
    print(f"❌ Error importing models: {e}")
    raise

# Initialize database and migrations
db.init_app(app)
migrate = Migrate(app, db)

with app.app_context():
    try:
        # Check if migrations folder exists
        if not os.path.exists('migrations'):
            from flask_migrate import init
            init()

             # Test database connection
        from sqlalchemy import text
        db.session.execute(text('SELECT 1'))
        
        db.create_all()
        print("✅ Database tables created successfully")
    except Exception as e:
        print(f"⚠️ Database initialization error: {e}")

# Login manager setup
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'warning'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Constants
MAX_SLOTS = 9

# ========== UTILITY FUNCTIONS ==========
def send_verification_email(user):
    """Send verification email using Resend.com API - ENHANCED"""
    print(f"📧 [EMAIL] Starting email send for: {user.email}")
    
    try:
        import requests
        
        # Check if Resend API key is available
        api_key = os.environ.get('RESEND_API_KEY')
        if not api_key:
            print("❌ [EMAIL] RESEND_API_KEY not set in environment variables")
            return False
        
        print(f"🔑 [EMAIL] Resend API Key: {api_key[:10]}...")

        # Generate token
        token = ts.dumps(user.email, salt='email-verify')
        print(f"🔐 [EMAIL] Token generated: {token[:20]}...")
        
        # Generate verification URL
        base_url = os.environ.get('RENDER_EXTERNAL_URL', 'http://localhost:5000')
        verification_url = f"{base_url}/verify-email/{token}"
        print(f"🌐 [EMAIL] Verification URL: {verification_url}")

        # Prepare email data
        email_data = {
            'from': 'Boardify <onboarding@resend.dev>',
            'to': [user.email],
            'subject': 'Verify Your Email - Boardify',
            'html': f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <style>
                        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                        .header {{ background: #4CAF50; color: white; padding: 20px; text-align: center; }}
                        .button {{ background: #4CAF50; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; display: inline-block; }}
                        .footer {{ margin-top: 20px; padding: 20px; background: #f9f9f9; }}
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="header">
                            <h1>Welcome to Boardify! 🎉</h1>
                        </div>
                        
                        <p>Hello {user.name},</p>
                        
                        <p>Thank you for registering with Boardify! Please verify your email address by clicking the button below:</p>
                        
                        <p style="text-align: center;">
                            <a href="{verification_url}" class="button">Verify Email Address</a>
                        </p>
                        
                        <p>Or copy and paste this link in your browser:<br>
                        <code>{verification_url}</code></p>
                        
                        <p><strong>⚠️ Important:</strong> This verification link will expire in 24 hours.</p>
                        
                        <div class="footer">
                            <p>If you didn't create an account with Boardify, please ignore this email.</p>
                            <p>Best regards,<br><strong>Boardify Team</strong></p>
                        </div>
                    </div>
                </body>
                </html>
            """
        }

        print(f"📤 [EMAIL] Sending request to Resend API...")
        
        # Resend API call
        response = requests.post(
            'https://api.resend.com/emails',
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json'
            },
            json=email_data,
            timeout=15  # Increased timeout
        )
        
        print(f"📨 [EMAIL] Resend API Response Status: {response.status_code}")
        
        if response.status_code == 200:
            response_data = response.json()
            print(f"✅ [EMAIL] Verification email sent successfully to {user.email}")
            print(f"📧 [EMAIL] Email ID: {response_data.get('id', 'Unknown')}")
            return True
        else:
            print(f"❌ [EMAIL] Resend API error: {response.status_code}")
            print(f"❌ [EMAIL] Error details: {response.text}")
            return False
            
    except requests.exceptions.Timeout:
        print("❌ [EMAIL] Request timeout - email sending took too long")
        return False
    except requests.exceptions.ConnectionError:
        print("❌ [EMAIL] Connection error - cannot reach Resend API")
        return False
    except Exception as e:
        print(f"❌ [EMAIL] Unexpected error: {type(e).__name__}: {str(e)}")
        return False
    
@app.route('/debug-email-send')
def debug_email_send():
    """Debug email sending in real-time"""
    try:
        # Create a test user object
        class TestUser:
            def __init__(self, email, name="Test User"):
                self.email = email
                self.name = name
        
        test_email = request.args.get('email', 'lebrontan2004@gmail.com')
        test_user = TestUser(test_email)
        
        # Test the email function directly
        result = send_verification_email(test_user)
        
        return jsonify({
            'email_sent': result,
            'user_email': test_user.email,
            'resend_key_set': bool(os.environ.get('RESEND_API_KEY')),
            'resend_key_preview': os.environ.get('RESEND_API_KEY', '')[:10] + '...' if os.environ.get('RESEND_API_KEY') else 'NOT_SET',
            'base_url': os.environ.get('RENDER_EXTERNAL_URL', 'http://localhost:5000')
        })
        
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/test-verification-email')
def test_verification_email():
    """Test the actual verification email function"""
    try:
        test_email = request.args.get('email', 'lebrontan2004@gmail.com')
        
        # Create a test user object
        class TestUser:
            def __init__(self, email, name="Test User"):
                self.email = email
                self.name = name
        
        test_user = TestUser(test_email)
        
        # Test the actual verification email
        result = send_verification_email(test_user)
        
        return jsonify({
            'success': result,
            'message': f'Verification email test completed for {test_email} - check your inbox and spam folder',
            'test_email': test_email
        })
        
    except Exception as e:
        return jsonify({'error': str(e)})


def verify_token(token, expiration=86400):
    """Verify the token and return email if valid - ENHANCED"""
    print(f"🔐 Verifying token: {token[:20]}...")
    try:
        email = ts.loads(token, salt='email-verify', max_age=expiration)
        print(f"✅ Token verified successfully for: {email}")
        return email
    except SignatureExpired:
        print("❌ Token expired")
        return None
    except BadSignature:
        print("❌ Invalid token signature")
        return None
    except Exception as e:
        print(f"❌ Token verification error: {e}")
        print(f"❌ Error type: {type(e).__name__}")
        return None

def allowed_file(file):
    """Check if file is allowed"""
    if not hasattr(file, 'filename'):
        return False
    filename = file.filename
    if not filename or '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return False
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size > app.config['MAX_CONTENT_LENGTH']:
        return False
    return True

def calculate_total_bill(property, start_date, end_date):
    """Calculate total bill for booking"""
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    total_days = (end - start).days + 1

    if total_days <= 0:
        raise ValueError("End date must be after start date.")

    total_bill = property.price * total_days
    return total_bill, total_days

def calculate_final_amount(amount, status, due_date, payment_date=None):
    """Calculate final amount with discount/penalty"""
    today = date.today()
    discount = 0
    penalty = 0
    if status.lower() == 'paid' and payment_date and payment_date <= due_date:
        discount = amount * 0.05
    elif status.lower() == 'unpaid' and due_date < today:
        penalty = amount * 0.1
    return amount - discount + penalty, discount, penalty

def get_recent_messages(user_id, limit=3):
    return (
        Message.query  # ✅ CORRECT
        .filter((Message.sender_id == user_id) | (Message.receiver_id == user_id))
        .order_by(Message.timestamp.desc())
        .limit(limit)
        .all()
    )

def verified_landlord_required(f):
    """Decorator to require verified landlord status"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash("Please login first.", "warning")
            return redirect(url_for('login'))
        
        if current_user.role != 'landlord':
            return f(*args, **kwargs)
        
        if not getattr(current_user, 'is_approved_by_admin', False):
            flash('⚠️ Your account is pending admin verification. You cannot access this feature until an admin approves your license document.', 'warning')
            return redirect(url_for('dashboard'))
        
        return f(*args, **kwargs)
    return decorated_function

def apply_penalties():
    """Apply penalties for late payments"""
    today = date.today()
    unpaid_bills = Billing.query.filter_by(status='unpaid').all()
    for bill in unpaid_bills:
        if bill.due_date and today > bill.due_date:
            days_late = (today - bill.due_date).days
            bill.penalty = days_late * 20
    db.session.commit()
    print("✅ Penalties updated.")

def apply_discounts():
    """Apply discounts for early payments"""
    paid_bills = Billing.query.filter_by(status='paid').all()
    for bill in paid_bills:
        if bill.due_date and bill.payment_method and bill.discount == 0:
            bill.discount = bill.amount * 0.05
    db.session.commit()
    print("💰 Discounts applied.")




# ========== REQUEST HANDLERS ==========

@app.before_request
def handle_free_tier():
    """Optimize for Render's free tier"""
    pass

@app.after_request
def add_security_headers(response):
    """Add security and cache headers"""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    
    if request.path in ['/dashboard', '/profile', '/billing', '/admin']:
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    else:
        response.headers['Cache-Control'] = 'public, max-age=300'
    
    return response



# ========== ROUTES ==========




@app.route('/health')
def health_check():
    """Health check endpoint for monitoring"""
    try:
        from sqlalchemy import text
        db.session.execute(text('SELECT 1'))
        db_status = "healthy"
    except Exception as e:
        print(f"Database health check error: {e}")
        db_status = "unhealthy"
    
    return jsonify({
        "status": "healthy" if db_status == "healthy" else "degraded",
        "service": "boardify.app",
        "database": db_status,
        "email": "enabled" if EMAIL_ENABLED else "disabled",
        "timestamp": datetime.utcnow().isoformat()
    })
@app.route('/')
def home():
    """Home page - redirect based on login status"""
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    """User registration - FIXED & IMPROVED"""
    if request.method == 'POST':
        try:
            print("🔍 [DEBUG] Registration form submitted")
            
            if not request.form.get('terms'):
                flash("You must agree to the terms and conditions to register.", "danger")
                return redirect(url_for('register'))

            # Get form data
            name = request.form['name'].strip()
            email = request.form['email'].strip().lower()
            password = request.form['password']
            role = request.form['role']
            gender = request.form['gender']
            birthdate_str = request.form['birthdate']

            # Validation
            if not all([name, email, password, role, gender, birthdate_str]):
                flash("All fields are required.", "danger")
                return redirect(url_for('register'))

            # Check if email already exists
            existing_user = User.query.filter_by(email=email).first()
            if existing_user:
                flash("Email already registered. Please use a different email or login.", "danger")
                return redirect(url_for('register'))

            # Birthdate validation
            try:
                birthdate = datetime.strptime(birthdate_str, '%Y-%m-%d').date()
                today = date.today()
                age = today.year - birthdate.year - ((today.month, today.day) < (birthdate.month, birthdate.day))
                if age < 18:
                    flash("You must be at least 18 years old to register.", "danger")
                    return redirect(url_for('register'))
            except ValueError:
                flash("Invalid birthdate format.", "danger")
                return redirect(url_for('register'))

            # Handle license file for landlords
            filename = None
            if role == 'landlord':
                license_file = request.files.get('permit')
                if license_file and license_file.filename:
                    if allowed_file(license_file):
                        original_filename = secure_filename(license_file.filename)
                        filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{original_filename}"
                        save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                        license_file.save(save_path)
                    else:
                        flash("Invalid license file. Please upload PNG, JPG, or JPEG under 5MB.", "danger")
                        return redirect(url_for('register'))

            # Create new user
            new_user = User(
                name=name,
                email=email,
                password_hash=generate_password_hash(password, method="pbkdf2:sha256"),
                role=role,
                gender=gender,
                birthdate=birthdate,
                license_image=filename,
                is_verified=False,  # Always start as unverified
                is_approved_by_admin=False if role == 'landlord' else True
            )
            
            db.session.add(new_user)
            db.session.commit()
            print(f"✅ [DEBUG] User created: {email}, ID: {new_user.id}")

            # Send verification email - IMPROVED LOGIC
            print(f"🔍 [DEBUG] EMAIL_ENABLED: {EMAIL_ENABLED}")
            
            if EMAIL_ENABLED:
                print(f"🔍 [DEBUG] Attempting to send verification email to: {email}")
                email_sent = send_verification_email(new_user)
                print(f"🔍 [DEBUG] Email send result: {email_sent}")
                
                if email_sent:
                    flash("🎉 Registration successful! Please check your email to verify your account before logging in.", "success")
                    print(f"✅ [DEBUG] Verification email sent successfully to {email}")
                else:
                    # Email failed to send - user can resend later
                    flash("✅ Registration successful! However, we couldn't send the verification email. Please use the 'Resend Verification' option on the login page.", "warning")
                    print(f"⚠️ [DEBUG] Email failed to send for {email}")
            else:
                # Email completely disabled - auto-verify user
                new_user.is_verified = True
                db.session.commit()
                flash("✅ Registration successful! You can now login.", "success")
                print(f"ℹ️ [DEBUG] Email disabled - auto-verified user: {email}")

            return redirect(url_for('login'))
            
        except Exception as e:
            db.session.rollback()
            print(f"❌ Registration error: {e}")
            import traceback
            traceback.print_exc()
            flash(f"Registration failed: {str(e)}", "danger")
            return redirect(url_for('register'))

    return render_template('register.html')

# @app.route('/test-resend-api-key')
# def test_resend_api_key():
#     """Test if Resend API key is valid"""
#     try:
#         import resend
        
#         api_key = os.environ.get('RESEND_API_KEY')
#         if not api_key:
#             return jsonify({"status": "error", "message": "API key not set"})
        
#         resend.api_key = api_key
        
#         # Try a simple API call to validate the key
#         try:
#             # This will fail if API key is invalid
#             params = {
#                 "from": "Boardify <onboarding@resend.dev>",
#                 "to": ["lebrontan2004@gmail.com"],
#                 "subject": "API Key Test",
#                 "html": "<p>Testing API key validity</p>"
#             }
#             result = resend.Emails.send(params)
            
#             return jsonify({
#                 "status": "success",
#                 "message": "✅ API key is VALID and working!",
#                 "email_id": result['id']
#             })
            
#         except Exception as api_error:
#             error_msg = str(api_error)
#             if "unauthorized" in error_msg.lower():
#                 return jsonify({
#                     "status": "invalid_key",
#                     "message": "❌ API key is INVALID or deactivated"
#                 })
#             elif "forbidden" in error_msg.lower():
#                 return jsonify({
#                     "status": "no_permission", 
#                     "message": "❌ API key doesn't have sending permissions"
#                 })
#             else:
#                 return jsonify({
#                     "status": "api_error",
#                     "message": f"❌ Resend API error: {error_msg}"
#                 })
                
#     except Exception as e:
#         return jsonify({
#             "status": "error",
#             "message": f"Test failed: {str(e)}"
#         }), 500
    

@app.route('/test-resend')
def test_resend():
    """Test Resend.com email sending"""
    try:
        # Check if requests is available
        try:
            import requests
        except ImportError:
            return "❌ 'requests' library not installed. Run: pip install requests"
        
        api_key = os.environ.get('RESEND_API_KEY')
        if not api_key:
            return "❌ RESEND_API_KEY environment variable not set"
        
        # Test the API key format
        if not api_key.startswith('re_'):
            return f"❌ API key format looks wrong. Should start with 're_'. Got: {api_key[:10]}..."
        
        response = requests.post(
            'https://api.resend.com/emails',
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json'
            },
            json={
                'from': 'Boardify <onboarding@resend.dev>',
                'to': ['lebrontan2004@gmail.com'],
                'subject': '🎉 Resend Test - Boardify Email Working!',
                'html': '<h2>Congratulations! 🎉</h2><p>Your Boardify email system is now working perfectly with Resend!</p><p>Users will receive verification emails instantly.</p>'
            },
            timeout=10
        )
        
        if response.status_code == 200:
            return "✅ Resend test email sent! Check your inbox (and spam folder)."
        else:
            error_detail = response.json() if response.text else "No error details"
            return f"❌ Resend test failed: {response.status_code} - {error_detail}"
            
    except requests.exceptions.Timeout:
        return "❌ Resend API timeout - request took too long"
    except requests.exceptions.ConnectionError:
        return "❌ Connection error - check your internet connection"
    except Exception as e:
        return f"❌ Resend test error: {type(e).__name__}: {str(e)}"


# @app.route('/debug-email-setup')
# def debug_email_setup():
#     """Comprehensive email debugging for Render"""
#     debug_info = {
#         'environment': {
#             'RENDER': bool(os.environ.get('RENDER')),
#             'RENDER_EXTERNAL_URL': os.environ.get('RENDER_EXTERNAL_URL'),
#             'FLASK_ENV': os.environ.get('FLASK_ENV'),
#         },
#         'email_config': {
#             'MAIL_SERVER': app.config.get('MAIL_SERVER'),
#             'MAIL_PORT': app.config.get('MAIL_PORT'),
#             'MAIL_USE_TLS': app.config.get('MAIL_USE_TLS'),
#             'MAIL_USE_SSL': app.config.get('MAIL_USE_SSL'),
#             'MAIL_USERNAME': 'SET' if app.config.get('MAIL_USERNAME') else 'MISSING',
#             'MAIL_PASSWORD': 'SET' if app.config.get('MAIL_PASSWORD') else 'MISSING',
#             'MAIL_DEFAULT_SENDER': app.config.get('MAIL_DEFAULT_SENDER'),
#         },
#         'app_config': {
#             'SECRET_KEY_SET': bool(app.config.get('SECRET_KEY')),
#             'EMAIL_ENABLED': EMAIL_ENABLED,
#             'SERVER_NAME': app.config.get('SERVER_NAME'),
#         }
#     }
    
#     # Test database connection
#     try:
#         from sqlalchemy import text
#         db.session.execute(text('SELECT 1'))
#         debug_info['database'] = 'Connected'
#     except Exception as e:
#         debug_info['database'] = f'Error: {str(e)}'
    
#     return jsonify(debug_info)



@app.route('/verify-email/<token>')
def verify_email(token):
    """Verify user email - FIXED"""
    email = verify_token(token)
    
    if email is None:
        flash("The verification link is invalid or has expired. Please request a new verification email.", "danger")
        return redirect(url_for('login'))
    
    user = User.query.filter_by(email=email).first()
    
    if user is None:
        flash("User not found.", "danger")
        return redirect(url_for('login'))
    
    if user.is_verified:
        flash("Your email is already verified. Please login.", "info")
        return redirect(url_for('login'))
    
    user.is_verified = True
    if hasattr(user, 'verification_token'):
        user.verification_token = None
    db.session.commit()
    
    flash("✅ Email verified successfully! You can now login to your account.", "success")
    return redirect(url_for('login'))

@app.route('/resend-verification', methods=['POST'])
def resend_verification():
    """Resend verification email - FIXED"""
    email = request.form.get('email', '').strip().lower()
    
    if not email:
        flash("Please provide your email address.", "warning")
        return redirect(url_for('login'))
    
    user = User.query.filter_by(email=email).first()
    
    if user:
        if user.is_verified:
            flash("Your email is already verified. You can login now.", "info")
            return redirect(url_for('login'))
        
        if not EMAIL_ENABLED:
            flash("Email service is not configured. Please contact support.", "danger")
            return redirect(url_for('login'))
        
        if send_verification_email(user):
            flash("✅ Verification email sent! Please check your inbox and spam folder.", "success")
        else:
            flash("Failed to send verification email. Please try again later or contact support.", "danger")
    else:
        # Don't reveal if email exists or not for security
        flash("If this email is registered, a verification link will be sent.", "info")
    
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    """User login - FIXED"""
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']
        
        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password_hash, password):
            if not user.is_verified and EMAIL_ENABLED:
                flash("⚠️ Please verify your email before logging in. Check your inbox for the verification link.", "warning")
                return render_template('login.html', show_resend=True, user_email=email)
                
            login_user(user)
            session['user_id'] = user.id
            session['user_role'] = user.role
            session['user_name'] = user.name
            session['user_verified'] = user.is_verified
            
            flash(f"Welcome back, {user.name}!", "success")
            
            # Redirect to intended page or dashboard
            next_page = request.args.get('next')
            if next_page:
                return redirect(next_page)
            return redirect(url_for('dashboard'))

        flash("Invalid email or password.", "danger")
        return redirect(url_for('login'))

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    """User logout"""
    session.pop('user_id', None)
    session.pop('user_role', None)
    session.pop('user_name', None)
    session.pop('user_verified', None)
    logout_user()
    flash("You have been logged out successfully.", "info")
    return redirect(url_for('login'))

@app.route('/dashboard', methods=['GET', 'POST'])
@login_required
def dashboard():
    """User dashboard"""
    user_id = session.get('user_id')
    user = User.query.get(user_id)

    if not user:
        flash("User not found. Please log in again.", "danger")
        return redirect(url_for('login'))

    if user.role == 'admin':
        total_users = User.query.count()
        total_landlords = User.query.filter_by(role='landlord').count()
        total_tenants = User.query.filter_by(role='tenant').count()
        total_properties = Property.query.count()
        pending_verifications = User.query.filter_by(role='landlord', is_approved_by_admin=False).count()
        pending_tickets = HelpSupport.query.filter_by(status='pending').count()
        
        paid_bills = Billing.query.filter_by(status='paid').all()
        total_commission = sum(bill.admin_commission or 0 for bill in paid_bills)
        unpaid_bills = Billing.query.filter_by(status='unpaid').all()
        pending_commission = sum(bill.amount * 0.05 for bill in unpaid_bills)
        
        recent_tickets = HelpSupport.query.order_by(HelpSupport.timestamp.desc()).limit(5).all()
        recent_users = User.query.order_by(User.created_at.desc()).limit(5).all()
        
        response = make_response(render_template(
            'admin_dashboard.html',
            user=user,
            total_users=total_users,
            total_landlords=total_landlords,
            total_tenants=total_tenants,
            total_properties=total_properties,
            pending_verifications=pending_verifications,
            pending_tickets=pending_tickets,
            total_commission=total_commission,
            pending_commission=pending_commission,
            recent_tickets=recent_tickets,
            recent_users=recent_users
        ))
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return response

    elif user.role == 'landlord':
        if request.method == 'POST':
            file = request.files.get('trend_image')
            if file and file.filename != "":
                import time
                filename = f"{int(time.time())}_{secure_filename(file.filename)}"
                upload_path = os.path.join('static/uploads', filename)
                file.save(upload_path)
                user.trend_image = filename
                db.session.commit()
                flash("Trend image uploaded successfully!", "success")
            return redirect(url_for('dashboard'))

        chart_image = getattr(user, 'trend_image', None)
        properties = Property.query.filter_by(landlord_id=user.id).all()
        property_ids = [p.id for p in properties]
        pending_bookings = Booking.query.filter(
            Booking.property_id.in_(property_ids),
            Booking.status == 'pending'
        ).all()
        
        tenant_bills = []
        for prop in properties:
            tenant_bills.extend(getattr(prop, 'bills', []))

        relevant_policies = Policy.query.filter(
            (Policy.applicable_role == user.role) | (Policy.applicable_role == 'all')
        ).all()

        response = make_response(render_template(
            'dashboard.html',
            user=user,
            properties=properties,
            pending_bookings=pending_bookings,
            tenant_bills=tenant_bills,
            chart_image=chart_image,
            policies=relevant_policies
        ))
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return response

    elif user.role == 'tenant':
        bookings = Booking.query.filter_by(tenant_id=user.id).all()
        pending_bookings = [b for b in bookings if b.status == 'pending']
        tenant_bills = Billing.query.filter_by(tenant_id=user.id).all()
        
        chart_image = None
        approved_booking = Booking.query.filter_by(tenant_id=user.id, status='approved').first()
        if approved_booking and approved_booking.property and approved_booking.property.owner:
            chart_image = getattr(approved_booking.property.owner, 'trend_image', None)

        relevant_policies = Policy.query.filter(
            (Policy.applicable_role == user.role) | (Policy.applicable_role == 'all')
        ).all()

        response = make_response(render_template(
            'dashboard.html',
            user=user,
            properties=bookings,
            pending_bookings=pending_bookings,
            tenant_bills=tenant_bills,
            chart_image=chart_image,
            policies=relevant_policies
        ))
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return response

    else:
        flash("Unknown user role. Please contact support.", "danger")
        return redirect(url_for('logout'))
    
# @app.route('/check-resend-config')
# def check_resend_config():
#     """Check Resend configuration"""
#     try:
#         config = {
#             'resend_api_key_set': bool(os.environ.get('RESEND_API_KEY')),
#             'resend_api_key_preview': os.environ.get('RESEND_API_KEY', '')[:10] + '...' if os.environ.get('RESEND_API_KEY') else 'NOT_SET',
#             'requirements_file_exists': os.path.exists('requirements.txt')
#         }
        
#         # Check if resend is in requirements.txt
#         if config['requirements_file_exists']:
#             with open('requirements.txt', 'r') as f:
#                 requirements_content = f.read()
#                 config['resend_in_requirements'] = 'resend' in requirements_content
#         else:
#             config['resend_in_requirements'] = False
        
#         # Test Resend import
#         try:
#             import resend
#             config['resend_import'] = 'SUCCESS'
#         except ImportError as e:
#             config['resend_import'] = f'FAILED: {str(e)}'
        
#         return jsonify(config)
        
#     except Exception as e:
#         return jsonify({'error': str(e)}), 500

    






@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    """User profile"""
    user = User.query.get(session.get('user_id'))
    if not user:
        flash("User not found.", "danger")
        return redirect(url_for('login'))

    if request.method == 'POST':
        new_name = request.form.get('name')
        if new_name:
            user.name = new_name
            session['user_name'] = new_name

        user.gender = request.form.get('gender')
        birthdate_str = request.form.get('birthdate')
        if birthdate_str:
            try:
                user.birthdate = datetime.strptime(birthdate_str, '%Y-%m-%d').date()
            except ValueError:
                flash("Invalid birthdate format.", "danger")

        new_email = request.form.get('email')
        if new_email and new_email != user.email:
            existing_user = User.query.filter_by(email=new_email).first()
            if existing_user and existing_user.id != user.id:
                flash("Email already registered to another account.", "danger")
            else:
                user.email = new_email
                if EMAIL_ENABLED:
                    user.is_verified = False
                    if send_verification_email(user):
                        flash("Email updated! Please verify your new email address.", "warning")
                    else:
                        flash("Email updated but verification email failed to send. Please contact support.", "warning")
                else:
                    flash("Email updated successfully!", "success")

        if hasattr(user, 'phone'):
            user.phone = request.form.get('phone')
        if hasattr(user, 'bio'):
            user.bio = request.form.get('bio')

        file = request.files.get('profile_pic')
        if file and file.filename != '':
            if allowed_file(file):
                filename = secure_filename(file.filename)
                unique_filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
                file.save(file_path)
                user.profile_pic = unique_filename
            else:
                flash("Invalid file type or file too large. Please use PNG, JPG, or JPEG files under 5MB.", "danger")

        if request.form.get('resend_verification'):
            if not user.is_verified and EMAIL_ENABLED:
                if send_verification_email(user):
                    flash("Verification email sent! Please check your inbox.", "success")
                else:
                    flash("Failed to send verification email. Please try again later.", "danger")
            else:
                flash("Your email is already verified.", "info")

        db.session.commit()
        flash("Profile updated successfully!", "success")
        return redirect(url_for('profile'))

    if user.role == 'landlord':
        properties = Property.query.filter_by(landlord_id=user.id).all()
        bookings = Booking.query.join(Property).filter(Property.landlord_id == user.id).all()
        bills = Billing.query.join(Property).filter(Property.landlord_id == user.id).all()
    else:
        properties = []
        bookings = Booking.query.filter_by(tenant_id=user.id).all()
        bills = Billing.query.filter_by(tenant_id=user.id).all()

    session['user_verified'] = user.is_verified

    age = None
    if user.birthdate:
        today = date.today()
        age = today.year - user.birthdate.year - ((today.month, today.day) < (user.birthdate.month, user.birthdate.day))

    return render_template(
        'profile.html',
        user=user,
        properties=properties,
        bookings=bookings,
        bills=bills,
        today=date.today(),
        age=age,
        verified=user.is_verified
    )


    
    # Test SMTP connection
    try:
        import smtplib
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=10)
        server.login(app.config['MAIL_USERNAME'], app.config['MAIL_PASSWORD'])
        server.quit()
        debug_info['smtp_test'] = 'SUCCESS'
    except Exception as e:
        debug_info['smtp_test'] = f'FAILED: {str(e)}'
    
    return jsonify(debug_info)

    
# @app.route('/debug-database')
# def debug_database():
#     """Debug database configuration"""
#     db_config = {
#         'database_url': app.config.get('SQLALCHEMY_DATABASE_URI', 'NOT SET'),
#         'database_type': 'PostgreSQL' if 'postgresql' in app.config.get('SQLALCHEMY_DATABASE_URI', '') else 'SQLite',
#         'render_database_url': bool(os.environ.get('DATABASE_URL'))
#     }
    
#     try:
#         from sqlalchemy import text  # ← ADD THIS IMPORT
#         db.session.execute(text('SELECT 1'))  # ← FIX THIS LINE
#         db_config['connection_test'] = 'SUCCESS'
#     except Exception as e:
#         db_config['connection_test'] = f'FAILED: {str(e)}'
    
#     return jsonify(db_config)




# @app.route('/debug-db-details')
# def debug_db_details():
#     """Detailed database debugging"""
#     import sqlalchemy as sa
    
#     config = {
#         'database_url_set': bool(os.environ.get('DATABASE_URL')),
#         'database_url_preview': os.environ.get('DATABASE_URL', '')[:30] + '...' if os.environ.get('DATABASE_URL') else 'NOT_SET',
#         'sqlalchemy_uri': app.config.get('SQLALCHEMY_DATABASE_URI', 'NOT SET')[:30] + '...',
#     }
    
#     try:
#         # Test connection
#         with db.engine.connect() as conn:
#             result = conn.execute(sa.text('SELECT version(), current_database(), current_user'))
#             db_info = result.fetchone()
            
#         config.update({
#             'status': '✅ CONNECTED',
#             'database_version': db_info[0],
#             'database_name': db_info[1],
#             'current_user': db_info[2]
#         })
        
#     except Exception as e:
#         config.update({
#             'status': '❌ CONNECTION FAILED',
#             'error': str(e),
#             'error_type': type(e).__name__
#         })
    
#     return jsonify(config)

# @app.route('/debug-config')
# def debug_config():
#     """Debug configuration without sensitive info"""
#     return jsonify({
#         "database_url": "SET" if app.config.get('SQLALCHEMY_DATABASE_URI') else "MISSING",
#         "secret_key": "SET" if app.config.get('SECRET_KEY') else "MISSING",
#         "email_enabled": EMAIL_ENABLED,
#         "mail_server": app.config.get('MAIL_SERVER'),
#         "mail_port": app.config.get('MAIL_PORT'),
#         "mail_username": app.config.get('MAIL_USERNAME'),
#         "mail_password_set": bool(app.config.get('MAIL_PASSWORD')),
#         "render_external_url": os.environ.get('RENDER_EXTERNAL_URL')
#     })

@app.route('/properties')
@login_required
def viewproperties():
    """View all properties"""
    user = User.query.get(session.get('user_id'))
    if not user:
        flash("User not found.", "danger")
        return redirect(url_for('login'))

    if user.role == 'landlord':
        properties = Property.query.filter_by(landlord_id=user.id).all()
    else:
        properties = Property.query.all()

    property_data = []
    for prop in properties:
        total_slots = prop.slots if prop.slots is not None else 10
        approved_bookings_count = sum(1 for booking in prop.bookings if booking.status == 'approved')
        slots_left = max(0, total_slots - approved_bookings_count)
        user_has_booked = any(b.tenant_id == user.id for b in prop.bookings)
        
        property_data.append({
            'property': prop,
            'slots_left': slots_left,
            'total_slots': total_slots,
            'user_has_booked': user_has_booked
        })

    return render_template('viewproperties.html', properties=property_data, user=user)

@app.route('/property_detail/<int:property_id>', methods=['GET'])
def property_detail(property_id):
    """Property detail page"""
    property = Property.query.get_or_404(property_id)

    user_booking = None
    user_review = None
    can_review = False
    
    if 'user_id' in session and session.get('user_role') == 'tenant':
        user_id = session['user_id']
        user_booking = Booking.query.filter_by(
            property_id=property.id,
            tenant_id=user_id
        ).all()
        
        user_review = Review.query.filter_by(
            property_id=property_id,
            tenant_id=user_id
        ).first()
        
        can_review = Booking.query.filter(
            Booking.property_id == property_id,
            Booking.tenant_id == user_id,
            Booking.status == 'approved'
        ).first() is not None and not user_review

    total_slots = property.slots if property.slots is not None else 10
    approved_bookings_count = sum(1 for booking in property.bookings if booking.status == 'approved')
    slots_left = max(0, total_slots - approved_bookings_count)

    reviews = Review.query.filter_by(property_id=property_id).join(User).order_by(Review.created_at.desc()).all()
    
    avg_rating = 0
    if reviews:
        avg_rating = sum(review.rating for review in reviews) / len(reviews)

    image_urls = [
        url_for('static', filename='uploads/' + img.filename) for img in property.images
    ] if property.images else [
        url_for('static', filename='uploads/' + (property.image or 'default.jpg'))
    ]

    return render_template(
        'property_detail.html',
        property=property,
        user_booking=user_booking,
        slots_left=slots_left,
        total_slots=total_slots,
        image_urls=image_urls,
        reviews=reviews,
        user_review=user_review,
        can_review=can_review,
        avg_rating=round(avg_rating, 1) if avg_rating > 0 else 0,
        review_count=len(reviews)
    )



@app.route('/add_property', methods=['GET', 'POST'])
@login_required
@verified_landlord_required
def add_property():
    """Add new property"""
    user = User.query.get(session.get('user_id'))
    
    if not user or user.role != 'landlord':
        flash("Only landlords can add properties.", "danger")
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        try:
            title = request.form.get('title', '').strip()
            description = request.form.get('description', '').strip()
            price = request.form.get('price', '0')
            location = request.form.get('location', '').strip()
            gender_preference = request.form.get('gender_preference')
            property_type = request.form.get('property_type')
            bedrooms = request.form.get('bedrooms', '0')
            bathrooms = request.form.get('bathrooms', '0')
            slots = request.form.get('slots', '10')
            amenities = request.form.getlist('amenities')

            required_fields = {
                'title': title,
                'description': description, 
                'price': price,
                'property_type': property_type,
                'slots': slots,
                'gender_preference': gender_preference
            }
            
            missing_fields = [field for field, value in required_fields.items() if not value]
            if missing_fields:
                flash(f"Missing required fields: {', '.join(missing_fields)}", "danger")
                return redirect(request.url)

            try:
                price = float(price)
                slots = int(slots)
                bedrooms = int(bedrooms) if bedrooms and bedrooms != '0' else None
                bathrooms = float(bathrooms) if bathrooms and bathrooms != '0' else None
            except ValueError as e:
                flash(f"Invalid number format: {str(e)}", "danger")
                return redirect(request.url)

            if price <= 0:
                flash("Price must be greater than 0.", "danger")
                return redirect(request.url)
                
            if slots <= 0:
                flash("Slots must be greater than 0.", "danger")
                return redirect(request.url)

            files = request.files.getlist('images')
            
            if len(files) > app.config['MAX_IMAGE_COUNT']:
                flash(f"Maximum {app.config['MAX_IMAGE_COUNT']} images allowed.", "danger")
                return redirect(request.url)

            main_image = None
            image_filenames = []
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

            for idx, file in enumerate(files):
                if file and file.filename != '':
                    if not allowed_file(file):
                        flash(f"File not allowed or too large: {file.filename}. Please use PNG, JPG, or JPEG files under 5MB.", "danger")
                        continue

                    original_filename = secure_filename(file.filename)
                    unique_filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{original_filename}"
                    upload_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)

                    try:
                        file.save(upload_path)
                        image_filenames.append(unique_filename)
                        if idx == 0:
                            main_image = unique_filename
                    except Exception as e:
                        flash(f"Error saving file {file.filename}", "danger")

            new_property = Property(
                title=title,
                description=description,
                price=price,
                location=location,
                gender_preference=gender_preference,
                property_type=property_type,
                bedrooms=bedrooms,
                bathrooms=bathrooms,
                slots=slots,
                image=main_image,
                landlord_id=user.id,
                amenities=','.join(amenities) if amenities else None
            )

            db.session.add(new_property)
            db.session.flush()

            for fname in image_filenames:
                if fname != main_image:
                    prop_image = PropertyImage(property_id=new_property.id, filename=fname)
                    db.session.add(prop_image)

            db.session.commit()
            flash("Property added successfully!", "success")
            return redirect(url_for('viewproperties'))
            
        except Exception as e:
            db.session.rollback()
            flash(f"Error adding property: {str(e)}", "danger")
            return redirect(request.url)

    return render_template('add_property.html', user=user)

@app.route('/edit-property/<int:property_id>', methods=['GET', 'POST'])
@login_required
def edit_property(property_id):
    """Edit property"""
    user_id = session.get('user_id')
    user = User.query.get(user_id)
    
    property_obj = Property.query.get_or_404(property_id)
    
    if user.role != 'landlord' or property_obj.landlord_id != user_id:
        flash('You do not have permission to edit this property.', 'danger')
        return redirect(url_for('viewproperties'))
    
    if request.method == 'POST':
        if request.form.get('action') == 'delete_image':
            return delete_image()
        
        try:
            property_obj.title = request.form.get('title')
            property_obj.description = request.form.get('description')
            property_obj.location = request.form.get('location')
            property_obj.price = float(request.form.get('price'))
            property_obj.slots = int(request.form.get('total_slots', request.form.get('slots', 10)))
            property_obj.gender_preference = request.form.get('gender_preference')
            property_obj.status = request.form.get('status', 'available')
            
            if 'images' in request.files:
                files = request.files.getlist('images')
                
                existing_count = PropertyImage.query.filter_by(property_id=property_id).count()
                if existing_count + len(files) > app.config['MAX_IMAGE_COUNT']:
                    flash(f"Maximum {app.config['MAX_IMAGE_COUNT']} images allowed per property.", "danger")
                    return redirect(url_for('edit_property', property_id=property_id))
                
                for idx, file in enumerate(files):
                    if file and file.filename != '' and allowed_file(file):
                        filename = secure_filename(file.filename)
                        unique_filename = f"{uuid.uuid4()}_{filename}"
                        file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
                        file.save(file_path)
                        
                        if idx == 0 and not property_obj.image:
                            property_obj.image = unique_filename
                        
                        new_image = PropertyImage(
                            property_id=property_id,
                            filename=unique_filename
                        )
                        db.session.add(new_image)
            
            db.session.commit()
            flash('Property updated successfully!', 'success')
            return redirect(url_for('viewproperties'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating property: {str(e)}', 'danger')
    
    property_images = PropertyImage.query.filter_by(property_id=property_id).all()
    
    return render_template('edit_property.html', 
                        property=property_obj, 
                        user=user,
                        images=property_images)

@app.route('/delete-image', methods=['POST'])
@login_required
def delete_image():
    """Delete property image"""
    user_id = session.get('user_id')
    user = User.query.get(user_id)
    
    if user.role != 'landlord':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    try:
        image_id = request.form.get('image_id')
        action = request.form.get('action')
        
        if action != 'delete_image' or not image_id:
            return jsonify({'success': False, 'message': 'Invalid request'}), 400
        
        image = PropertyImage.query.get(image_id)
        
        if not image:
            return jsonify({'success': False, 'message': 'Image not found'}), 404
        
        property_obj = Property.query.get(image.property_id)
        if not property_obj or property_obj.landlord_id != user_id:
            return jsonify({'success': False, 'message': 'Unauthorized'}), 403
        
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], image.filename)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as e:
                print(f"Error deleting file: {e}")
        
        if property_obj.image == image.filename:
            remaining_images = PropertyImage.query.filter(
                PropertyImage.property_id == property_obj.id,
                PropertyImage.id != image.id
            ).first()
            
            if remaining_images:
                property_obj.image = remaining_images.filename
            else:
                property_obj.image = None
        
        db.session.delete(image)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Image deleted successfully'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Error: {str(e)}'}), 500

@app.route('/delete-property/<int:property_id>', methods=['POST'])
@login_required
def delete_property(property_id):
    """Delete property"""
    user_id = session.get('user_id')
    user = User.query.get(user_id)
    
    property_obj = Property.query.get_or_404(property_id)
    
    if user.role != 'landlord' or property_obj.landlord_id != user_id:
        return jsonify({'success': False, 'message': 'You do not have permission to delete this property.'}), 403
    
    try:
        property_images = PropertyImage.query.filter_by(property_id=property_id).all()
        for img in property_images:
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], img.filename)
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception as e:
                    print(f"Error deleting image file {img.filename}: {e}")
            db.session.delete(img)
        
        if property_obj.image:
            main_image_path = os.path.join(app.config['UPLOAD_FOLDER'], property_obj.image)
            if os.path.exists(main_image_path):
                try:
                    os.remove(main_image_path)
                except Exception as e:
                    print(f"Error deleting main image: {e}")
        
        Booking.query.filter_by(property_id=property_id).delete()
        Billing.query.filter_by(property_id=property_id).delete()
        Review.query.filter_by(property_id=property_id).delete()
        
        db.session.delete(property_obj)
        db.session.commit()
        
        count_after = Property.query.filter_by(landlord_id=user.id).count()
        
        return jsonify({
            'success': True, 
            'message': 'Property deleted successfully',
            'new_count': count_after
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Error deleting property: {str(e)}'}), 500
    

@app.route('/admin/delete-user/<email>')
def delete_user_by_email(email):
    """Delete specific user by email"""
    try:
        user = User.query.filter_by(email=email).first()
        if user:
            # Delete related records first
            Booking.query.filter_by(tenant_id=user.id).delete()
            Billing.query.filter_by(tenant_id=user.id).delete()
            
            # Delete the user
            db.session.delete(user)
            db.session.commit()
            
            return f"✅ Deleted user: {email}"
        else:
            return f"❌ User {email} not found"
    except Exception as e:
        db.session.rollback()
        return f"❌ Error: {str(e)}"

@app.route('/book_property/<int:property_id>', methods=['POST'])
@login_required
def book_property(property_id):
    """Book a property"""
    property = Property.query.get_or_404(property_id)
    
    start_date = request.form.get('start_date')
    end_date = request.form.get('end_date')
    
    if not start_date or not end_date:
        flash("Please provide both start and end dates.", "danger")
        return redirect(url_for('property_detail', property_id=property.id))
    
    try:
        start_date_obj = datetime.strptime(start_date, "%Y-%m-%d").date()
        end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").date()
        
        if end_date_obj <= start_date_obj:
            flash("End date must be after start date.", "danger")
            return redirect(url_for('property_detail', property_id=property.id))
            
    except ValueError as e:
        flash("Invalid date format. Please use YYYY-MM-DD.", "danger")
        return redirect(url_for('property_detail', property_id=property.id))
    
    active_bookings = Booking.query.filter(
        Booking.property_id == property.id,
        Booking.status.in_(["pending", "approved"]),
        Booking.start_date <= end_date_obj,
        Booking.end_date >= start_date_obj
    ).count()
    
    available_slots = MAX_SLOTS - active_bookings
    if available_slots <= 0:
        flash("Sorry, this property is fully booked for the selected dates.", "danger")
        return redirect(url_for('property_detail', property_id=property.id))
    
    total_days = (end_date_obj - start_date_obj).days
    monthly_rate = property.price
    daily_rate = monthly_rate / 30
    total_bill = total_days * daily_rate
    
    booking = Booking(
        property_id=property.id,
        tenant_id=current_user.id,
        start_date=start_date_obj,
        end_date=end_date_obj,
        status='pending',
        total_bill=total_bill
    )
    db.session.add(booking)
    db.session.flush()
    
    billing = Billing(
        tenant_id=current_user.id,
        property_id=property.id,
        amount=total_bill,
        status='unpaid',
        due_date=end_date_obj,
        booking_reference=booking.reference_number
    )
    db.session.add(billing)
    db.session.commit()
    
    flash(
        f"Booking requested successfully! Your booking reference is: <strong>{booking.reference_number}</strong><br>"
        f"{total_days} days × ₱{daily_rate:.2f}/day = ₱{total_bill:,.2f}. Waiting for approval.", 
        "success"
    )
    
    return redirect(url_for('booking_confirmation', reference_number=booking.reference_number))

@app.route('/booking/confirmation/<reference_number>')
@login_required
def booking_confirmation(reference_number):
    """Booking confirmation page"""
    booking = Booking.query.filter_by(reference_number=reference_number).first_or_404()
    
    if booking.tenant_id != current_user.id and current_user.role != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('dashboard'))
    
    return render_template('booking_confirmation.html', 
                        booking=booking, 
                        user=current_user)

@app.route('/search_booking', methods=['GET'])
@login_required
def search_booking():
    """Search booking by reference"""
    reference_number = request.args.get('reference', '').strip().upper()
    
    if reference_number:
        booking = Booking.query.filter_by(reference_number=reference_number).first()
        
        if booking:
            if booking.tenant_id == current_user.id or current_user.role in ['admin', 'landlord']:
                return redirect(url_for('booking_details', reference_number=reference_number))
            else:
                flash("Access denied to this booking.", "danger")
        else:
            flash("Booking reference not found.", "danger")
    
    recent_bookings = []
    if current_user.role == 'tenant':
        recent_bookings = Booking.query.filter_by(tenant_id=current_user.id)\
            .order_by(Booking.created_at.desc())\
            .limit(5)\
            .all()
    
    return render_template('search_booking.html', 
                        user=current_user, 
                        recent_bookings=recent_bookings)

@app.route('/booking/details/<reference_number>')
@login_required
def booking_details(reference_number):
    """Booking details page"""
    booking = Booking.query.filter_by(reference_number=reference_number).first_or_404()
    
    if not (booking.tenant_id == current_user.id or 
            current_user.role == 'admin' or 
            (current_user.role == 'landlord' and booking.property.landlord_id == current_user.id)):
        flash("Access denied.", "danger")
        return redirect(url_for('dashboard'))
    
    billing = Billing.query.filter_by(booking_reference=reference_number).all()
    
    return render_template('booking_details.html', 
                        booking=booking, 
                        billing=billing,
                        user=current_user)

@app.route('/pending_bookings')
@login_required
@verified_landlord_required
def pending_bookings():
    """View pending bookings (landlord)"""
    user = User.query.get(session['user_id'])
    if user.role != 'landlord':
        flash("Access denied.", "danger")
        return redirect(url_for('dashboard'))
    
    properties = Property.query.filter_by(landlord_id=user.id).all()
    property_ids = [p.id for p in properties]
    
    bookings = Booking.query.filter(
        Booking.property_id.in_(property_ids),
        Booking.status == 'pending'
    ).order_by(Booking.created_at.desc()).all()
    
    return render_template('pending_bookings.html', bookings=bookings, user=user)

@app.route('/landlord/booking_action/<int:booking_id>/<action>', methods=['POST'])
@login_required
def booking_action(booking_id, action):
    """Approve or reject booking"""
    user = User.query.get(session['user_id'])
    
    if user.role != 'landlord':
        flash("Access denied.", "danger")
        return redirect(url_for('dashboard'))

    booking = Booking.query.get_or_404(booking_id)

    if booking.property.landlord_id != user.id:
        flash("You cannot modify this booking.", "danger")
        return redirect(url_for('pending_bookings'))

    if action == 'approve':
        booking.status = 'approved'
        booking.property.status = 'booked'

        existing_bill = Billing.query.filter_by(
            tenant_id=booking.tenant_id,
            property_id=booking.property_id
        ).first()

        if not existing_bill:
            new_bill = Billing(
                tenant_id=booking.tenant_id,
                property_id=booking.property_id,
                amount=booking.total_bill if booking.total_bill else booking.property.price,
                status='unpaid'
            )
            db.session.add(new_bill)

        flash(f"Booking for '{booking.property.title}' by {booking.tenant.name} approved.", "success")

    elif action == 'reject':
        booking.status = 'rejected'
        flash(f"Booking for '{booking.property.title}' by {booking.tenant.name} rejected.", "danger")

    else:
        flash("Invalid action.", "danger")
        return redirect(url_for('pending_bookings'))

    db.session.commit()
    return redirect(url_for('pending_bookings'))

@app.route('/landlord/approved_bookings')
@login_required
@verified_landlord_required 
def approved_bookings():
    """View approved bookings"""
    user = User.query.get(session.get('user_id'))

    if not user or user.role != 'landlord':
        flash("Access denied. You must be a landlord to view this page.", "danger")
        return redirect(url_for('dashboard'))

    properties = Property.query.filter_by(landlord_id=user.id).all()
    property_ids = [p.id for p in properties]

    bookings = Booking.query.filter(
        Booking.property_id.in_(property_ids),
        Booking.status == 'approved'
    ).all()

    return render_template('approved_bookings.html', bookings=bookings, user=user)

@app.route('/landlord/booked_properties')
@login_required
@verified_landlord_required
def booked_properties():
    """View all booked properties"""
    user = User.query.get(session.get('user_id'))

    if not user or user.role != 'landlord':
        flash("Access denied. You must be a landlord to view this page.", "danger")
        return redirect(url_for('home'))

    properties = Property.query.filter_by(landlord_id=user.id).all()

    booked_properties = []

    for prop in properties:
        for booking in prop.bookings:
            booked_properties.append({
                'id': booking.id,
                'property': prop,
                'tenant': booking.tenant,
                'start_date': booking.start_date,
                'end_date': booking.end_date,
                'status': booking.status
            })

    return render_template('booked_properties.html', booked_properties=booked_properties, user=user)

@app.route('/reject_booking/<int:booking_id>', methods=['POST'])
@login_required
def reject_booking(booking_id):
    """Reject a booking"""
    user = User.query.get(session['user_id'])
    if user.role != 'landlord':
        flash("Access denied.", "danger")
        return redirect(url_for('dashboard'))

    booking = Booking.query.get_or_404(booking_id)

    if booking.property.landlord_id != user.id:
        flash("You cannot reject this booking.", "danger")
        return redirect(url_for('booked_properties'))

    booking.status = 'rejected'
    db.session.commit()
    flash(f"Booking for {booking.property.title} has been rejected.", "danger")
    return redirect(url_for('booked_properties'))

@app.route('/my_bookings')
@login_required
def my_bookings_tenant():
    """Tenant's bookings"""
    user = User.query.get(session['user_id'])

    if not user or user.role != 'tenant':
        flash("Access denied. You must be a tenant to view this page.", "danger")
        return redirect(url_for('dashboard'))

    bookings = Booking.query.filter_by(tenant_id=user.id).order_by(Booking.created_at.desc()).all()

    return render_template('my_bookings_tenant.html', bookings=bookings, user=user)



@app.route('/billing')
@login_required
def billing():
    """Billing page"""
    user = current_user
    current_year = date.today().year

    if user.role == 'landlord':
        bills = Billing.query.join(Property).filter(Property.landlord_id == user.id).all()
    else:
        bills = Billing.query.filter_by(tenant_id=user.id).all()

    for bill in bills:
        if bill.status.lower() == 'unpaid' and bill.due_date:
            if date.today() > bill.due_date:
                bill.penalty = bill.amount * 0.1
                bill.status = 'overdue'
            else:
                bill.penalty = 0
        
        if bill.status.lower() == 'paid' and hasattr(bill, 'payment_date') and bill.due_date:
            if bill.payment_date <= bill.due_date:
                bill.discount = bill.amount * 0.05
            else:
                bill.discount = 0

    db.session.commit()

    return render_template('billing.html', bills=bills, user=user, current_year=current_year)

@app.route('/confirm_payment/<int:bill_id>', methods=['POST'])
@login_required
def confirm_payment(bill_id):
    """Confirm payment"""
    user = User.query.get(session['user_id'])
    if user.role != 'tenant':
        flash("You are not allowed to perform this action.", "danger")
        return redirect(url_for('billing'))

    bill = Billing.query.get_or_404(bill_id)
    if bill.status == 'paid':
        flash("This bill has already been paid.", "info")
        return redirect(url_for('billing'))

    payment_method = request.form.get('payment_method')
    if not payment_method:
        flash("Please select a payment method.", "warning")
        return redirect(url_for('billing'))

    total_amount = (bill.amount * (bill.months or 1)) + (bill.penalty or 0) - (bill.discount or 0)
    bill.admin_commission = total_amount * 0.05
    bill.status = 'paid'
    bill.payment_method = payment_method
    bill.payment_date = date.today()

    db.session.commit()

    flash(f"Bill {bill.id} has been paid! Total: ₱{total_amount:.2f}, Admin Commission: ₱{bill.admin_commission:.2f}", "success")
    return redirect(url_for('billing'))

@app.route('/pay_bill/<int:bill_id>', methods=['POST'])
@login_required
def pay_bill(bill_id):
    """Pay a bill"""
    user = User.query.get(session['user_id'])
    if user.role != 'landlord':
        flash("You are not allowed to perform this action.", "danger")
        return redirect(url_for('billing'))

    bill = Billing.query.get_or_404(bill_id)
    if bill.status == 'paid':
        flash("This bill has already been paid.", "info")
        return redirect(url_for('billing'))

    today = date.today()
    discount = 0
    penalty = 0

    if bill.due_date:
        if today <= bill.due_date:
            discount = bill.amount * 0.05
        else:
            days_late = (today - bill.due_date).days
            penalty = days_late * 50

    final_amount = bill.amount - discount + penalty

    bill.status = 'paid'
    bill.discount = discount
    bill.penalty = penalty
    bill.payment_date = today
    db.session.commit()

    flash(f"Bill {bill.id} marked as paid! Final amount: ₱{final_amount:.2f}", "success")
    return redirect(url_for('billing'))

@app.route('/bills/<int:user_id>')
def bills_page(user_id):
    """Bills page"""
    user = User.query.get_or_404(user_id)

    if user.role == 'landlord':
        bills = Billing.query.join(Property).filter(Property.landlord_id == user.id).all()
    else:
        bills = Billing.query.filter_by(tenant_id=user.id).all()

    for bill in bills:
        bill.current_penalty = 0
        bill.current_discount = 0

        if bill.status.lower() == 'paid' and bill.due_date and hasattr(bill, 'payment_date'):
            if bill.payment_date <= bill.due_date:
                bill.current_discount = bill.amount * 0.05

        elif bill.status.lower() == 'unpaid' and bill.due_date:
            if date.today() > bill.due_date:
                bill.current_penalty = bill.amount * 0.1

    return render_template('bills.html', bills=bills, user=user)

@app.route('/monthly_invoice', methods=['GET', 'POST'])
@login_required
def monthly_invoice():
    """Monthly invoice"""
    user = current_user
    if not user:
        flash("Please login first.", "danger")
        return redirect(url_for('login'))

    selected_year = request.args.get('year', date.today().year, type=int)
    selected_month = request.args.get('month', date.today().month, type=int)

    if user.role == 'landlord':
        bills = Billing.query.join(Property).filter(
            Property.landlord_id == user.id,
            db.extract('year', Billing.due_date) == selected_year,
            db.extract('month', Billing.due_date) == selected_month
        ).all()
    else:
        bills = Billing.query.filter(
            Billing.tenant_id == user.id,
            db.extract('year', Billing.due_date) == selected_year,
            db.extract('month', Billing.due_date) == selected_month
        ).all()

    total_amount = sum(b.amount for b in bills)
    total_discount = sum(b.amount * 0.05 if b.status.lower() == 'paid' and b.due_date >= b.payment_date else 0 for b in bills if hasattr(b, 'payment_date'))
    total_penalty = sum((date.today() - b.due_date).days * 50 if b.status.lower() == 'unpaid' and b.due_date < date.today() else 0 for b in bills if b.due_date)

    return render_template(
        'monthly_invoice.html',
        bills=bills,
        total_amount=total_amount,
        total_discount=total_discount,
        total_penalty=total_penalty,
        selected_year=selected_year,
        selected_month=selected_month,
        user=user
    )

@app.route('/admin/commissions')
@login_required
def admin_commissions():
    """Admin commission dashboard"""
    user = User.query.get(session['user_id'])
    if user.role != 'admin':
        flash("You are not allowed to access this page.", "danger")
        return redirect(url_for('dashboard'))

    paid_bills = Billing.query.filter_by(status='paid').all()
    total_commission = sum(bill.admin_commission or 0 for bill in paid_bills)
    
    unpaid_bills = Billing.query.filter_by(status='unpaid').all()
    pending_commission = sum(bill.amount * 0.05 for bill in unpaid_bills)
    
    properties_count = Property.query.count()
    tenants_count = User.query.filter_by(role='tenant').count()

    return render_template('admin_commissions.html', 
                        total_commission=total_commission,
                        pending_commission=pending_commission,
                        properties_count=properties_count,
                        tenants_count=tenants_count,
                        bills=paid_bills,
                        user=user)

@app.route('/process_payment', methods=['POST'])
def process_payment():
    """Process payment"""
    method = request.form.get('payment_method')
    flash(f'You selected {method} as your payment method!', 'success')
    return redirect(url_for('billing'))

@app.route('/gcash')
def gcash_page():
    return render_template("gcash.html")

@app.route('/maya')
def maya_page():
    return render_template("maya.html")

@app.route('/paypal')
def paypal_page():
    return render_template("paypal.html")

@app.route('/bank')
def bank_page():
    return render_template("bank.html")

@app.route('/add_review/<int:property_id>', methods=['POST'])
@login_required
def add_review(property_id):
    """Add review for property"""
    user = User.query.get(session['user_id'])
    property = Property.query.get_or_404(property_id)
    
    has_approved_booking = Booking.query.filter(
        Booking.property_id == property_id,
        Booking.tenant_id == user.id,
        Booking.status == 'approved'
    ).first()
    
    if not has_approved_booking:
        flash("You can only review properties you have an approved booking for.", "warning")
        return redirect(url_for('property_detail', property_id=property_id))
    
    existing_review = Review.query.filter_by(
        property_id=property_id,
        tenant_id=user.id
    ).first()
    
    if existing_review:
        flash("You have already reviewed this property.", "warning")
        return redirect(url_for('property_detail', property_id=property_id))
    
    rating = request.form.get('rating')
    comment = request.form.get('comment', '').strip()
    
    if not rating:
        flash("Please provide a rating.", "danger")
        return redirect(url_for('property_detail', property_id=property_id))
    
    new_review = Review(
        property_id=property_id,
        tenant_id=user.id,
        rating=int(rating),
        comment=comment
    )
    
    db.session.add(new_review)
    db.session.commit()
    
    flash("Thank you for your review! Other tenants can now see your feedback.", "success")
    return redirect(url_for('property_detail', property_id=property_id))

@app.route('/edit_review/<int:review_id>', methods=['GET', 'POST'])
@login_required
def edit_review(review_id):
    """Edit review"""
    review = Review.query.get_or_404(review_id)
    user = User.query.get(session['user_id'])
    
    if review.tenant_id != user.id:
        flash("You can only edit your own reviews.", "danger")
        return redirect(url_for('property_detail', property_id=review.property_id))
    
    if request.method == 'POST':
        review.rating = int(request.form.get('rating'))
        review.comment = request.form.get('comment', '').strip()
        db.session.commit()
        flash("Review updated successfully!", "success")
        return redirect(url_for('property_detail', property_id=review.property_id))
    
    return render_template('edit_review.html', review=review, user=user)

@app.route('/delete_review/<int:review_id>', methods=['POST'])
@login_required
def delete_review(review_id):
    """Delete review"""
    review = Review.query.get_or_404(review_id)
    user = User.query.get(session['user_id'])
    property_id = review.property_id
    
    if review.tenant_id != user.id and user.role != 'admin':
        flash("You can only delete your own reviews.", "danger")
        return redirect(url_for('property_detail', property_id=property_id))
    
    db.session.delete(review)
    db.session.commit()
    flash("Review deleted successfully!", "success")
    return redirect(url_for('property_detail', property_id=property_id))

@app.route("/inbox")
@login_required
def inbox():
    my_id = session["user_id"]
    chat_partners = (
        db.session.query(User)
        .join(Message, or_(Message.sender_id == User.id, Message.receiver_id == User.id))  # ✅ CORRECT
        .filter(or_(Message.sender_id == my_id, Message.receiver_id == my_id))  # ✅ CORRECT
        .filter(User.id != my_id)
        .distinct()
        .all()
    )
    return render_template("inbox.html", partners=chat_partners)

@app.route('/send_message/<int:receiver_id>', methods=['POST'])
@login_required
def send_message(receiver_id):
    """Send message"""
    if 'user_id' not in session:
        flash("Please log in first.")
        return redirect(url_for('login'))

    sender_id = session['user_id']
    content = request.form.get('content')

    if content.strip() == "":
        flash("Message cannot be empty.")
        return redirect(url_for('messages', user_id=receiver_id))

    new_message = Message(sender_id=sender_id, receiver_id=receiver_id, content=content)
    db.session.add(new_message)
    db.session.commit()

    return redirect(url_for('messages', user_id=receiver_id))



@app.route("/messages/<int:user_id>", methods=["GET", "POST"])
@login_required
def messages(user_id):
    """View and send messages"""
    my_id = session["user_id"]
    other = User.query.get_or_404(user_id)

    if request.method == "POST":
        content = request.form.get("content", "").strip()
        if content:
            db.session.add(Message(sender_id=my_id, receiver_id=other.id, content=content))
            db.session.commit()
            flash("Message sent!", "success")
        else:
            flash("Message cannot be empty.", "warning")
        return redirect(url_for("messages", user_id=other.id))

    chat = (
        Message.query
        .filter(
            or_(
                (Message.sender_id == my_id) & (Message.receiver_id == other.id),
                (Message.sender_id == other.id) & (Message.receiver_id == my_id),
            )
        )
        .order_by(Message.timestamp.asc())
        .all()
    )

    return render_template("messages.html", chat=chat, other=other)

@app.route("/users")
@login_required
def users():
    """View all users"""
    all_users = User.query.all()
    return render_template("users.html", users=all_users)

@app.route('/policies')
@login_required
def policies():
    """View policies"""
    user = User.query.get(session['user_id'])
    if not user:
        flash("User not found. Please log in again.", "danger")
        return redirect(url_for('login'))

    relevant_policies = Policy.query.filter(
        (Policy.applicable_role == user.role) | (Policy.applicable_role == 'all')
    ).all()

    return render_template('policies.html', user=user, policies=relevant_policies)

@app.route('/add_policy', methods=['GET', 'POST'])
@login_required
def add_policy():
    """Add policy (landlord/admin)"""
    user = User.query.get(session['user_id'])
    if user.role != 'landlord':
        flash("You are not allowed to add policies.", "danger")
        return redirect(url_for('policies'))

    if request.method == 'POST':
        title = request.form.get('title')
        content = request.form.get('content')
        applicable_role = request.form.get('applicable_role')

        if not title or not content or not applicable_role:
            flash("All fields are required.", "danger")
        else:
            new_policy = Policy(title=title, content=content, applicable_role=applicable_role)
            db.session.add(new_policy)
            db.session.commit()
            flash("Policy added successfully!", "success")
            return redirect(url_for('policies'))

    return render_template('add_policy.html', user=user)

@app.route('/help_support', methods=['GET', 'POST'])
@login_required
def help_support():
    """Help and support ticket submission"""
    user = User.query.get(session['user_id'])

    if request.method == 'POST':
        subject = request.form.get('subject')
        message = request.form.get('message')

        if not subject or not message:
            flash("All fields are required.", "danger")
        else:
            new_ticket = HelpSupport(user_id=user.id, subject=subject, message=message)
            db.session.add(new_ticket)
            db.session.commit()

            flash("Your message has been sent! We'll get back to you soon.", "success")
            return redirect(url_for('dashboard'))

    return render_template('help_support.html', user=user)

@app.route('/support_tickets')
@login_required
def support_tickets():
    """View all support tickets (admin)"""
    user = User.query.get(session['user_id'])

    if user.role != 'admin':
        flash("You are not allowed to view support tickets.", "danger")
        return redirect(url_for('dashboard'))

    tickets = HelpSupport.query.order_by(HelpSupport.timestamp.desc()).all()
    return render_template('support_tickets.html', tickets=tickets, user=user)

@app.route('/my_tickets')
@login_required
def my_tickets():
    """View user's own tickets"""
    user = User.query.get(session['user_id'])
    tickets = HelpSupport.query.filter_by(user_id=user.id).order_by(HelpSupport.timestamp.desc()).all()
    return render_template('my_tickets.html', tickets=tickets, user=user)

@app.route('/admin/help_tickets', methods=['GET', 'POST'])
@login_required
def admin_help_tickets():
    """Admin help ticket management"""
    user = User.query.get(session['user_id'])
    
    if user.role != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        ticket_id = request.form.get('ticket_id')
        new_status = request.form.get('status')
        ticket = HelpSupport.query.get(ticket_id)
        if ticket and new_status in ['pending', 'resolved']:
            ticket.status = new_status
            db.session.commit()
            flash(f"Ticket '{ticket.subject}' updated to {new_status}.", "success")
        return redirect(url_for('admin_help_tickets'))

    tickets = HelpSupport.query.order_by(HelpSupport.timestamp.desc()).all()
    return render_template('admin_help_tickets.html', tickets=tickets, user=user)

@app.route('/admin/help_support')
@login_required
def admin_help_support():
    """Admin help support dashboard"""
    user = User.query.get(session['user_id'])
    if user.role != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('dashboard'))

    tickets = HelpSupport.query.order_by(HelpSupport.timestamp.desc()).all()
    return render_template('admin_help_support.html', tickets=tickets)

@app.route('/admin/verify')
@login_required
def admin_verify():
    """Admin verification dashboard"""
    if current_user.role != 'admin':
        flash("Unauthorized access!", "danger")
        return redirect(url_for('dashboard'))

    unverified_landlords = User.query.filter_by(role='landlord').filter(
        (User.is_approved_by_admin == False) | (User.is_verified == False)
    ).all()
    return render_template('admin_verify.html', unverified_users=unverified_landlords)

@app.route('/admin/verify/<int:user_id>', methods=['POST'])
@login_required
def verify_landlord(user_id):
    """Approve landlord"""
    if current_user.role != 'admin':
        flash("Unauthorized access!", "danger")
        return redirect(url_for('dashboard'))

    user = User.query.get_or_404(user_id)
    user.is_approved_by_admin = True
    user.is_verified = True
    db.session.commit()
    flash(f"Landlord {user.name} has been approved by admin!", "success")
    return redirect(url_for('admin_verify'))



@app.route('/admin/reject/<int:user_id>', methods=['POST'])
@login_required
def reject_landlord(user_id):
    """Reject landlord"""
    if current_user.role != 'admin':
        flash("Unauthorized access!", "danger")
        return redirect(url_for('dashboard'))

    user = User.query.get_or_404(user_id)
    user.is_approved_by_admin = False
    db.session.commit()
    flash(f"Landlord {user.name} has been rejected by admin.", "warning")
    return redirect(url_for('admin_verify'))

@app.route('/upload_trend', methods=['POST'])
@login_required
def upload_trend():
    """Upload trend image"""
    if 'file' not in request.files:
        flash("No file part", "danger")
        return redirect(url_for('dashboard'))

    file = request.files['file']
    if file.filename == '':
        flash("No selected file", "danger")
        return redirect(url_for('dashboard'))

    if not allowed_file(file):
        flash("Invalid file type or size exceeds 5MB!", "danger")
        return redirect(url_for('dashboard'))

    user_trend_count = len(os.listdir(app.config['UPLOAD_FOLDER']))
    if user_trend_count >= app.config['MAX_IMAGE_COUNT']:
        flash(f"Maximum {app.config['MAX_IMAGE_COUNT']} images allowed!", "danger")
        return redirect(url_for('dashboard'))

    filename = secure_filename(file.filename)
    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
    flash("Trend image uploaded successfully!", "success")

    return redirect(url_for('dashboard'))


@app.route('/export-data')
@login_required
def export_data():
    """Export user data"""
    flash('Data export feature is coming soon!', 'info')
    return redirect(url_for('profile'))

@app.route('/buy_property/<int:property_id>', methods=['POST'])
def buy_property(property_id):
    """Buy/book property"""
    property = Property.query.get_or_404(property_id)
    property.status = 'booked'
    db.session.commit()
    flash(f"Property {property.title} has been booked!", "success")
    return redirect(url_for('dashboard'))

# ========== DATABASE INITIALIZATION ==========

# Ensure required directories exist
os.makedirs(os.path.join(BASE_DIR, 'instance'), exist_ok=True)
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

with app.app_context():
    try:
        db.create_all()
        print("✅ Database tables created successfully")
        
        # Create admin account from environment variables
        admin_email = os.environ.get('ADMIN_EMAIL')
        admin_password = os.environ.get('ADMIN_PASSWORD')
        
        if admin_email and admin_password:
            admin = User.query.filter_by(email=admin_email).first()
            if not admin:
                admin = User(
                    name="Boardify Admin",
                    email=admin_email,
                    password_hash=generate_password_hash(admin_password, method="pbkdf2:sha256"),
                    role="admin",
                    is_verified=True,
                    is_approved_by_admin=True,
                    gender="Prefer not to say",
                    birthdate=date(1990, 1, 1)
                )
                db.session.add(admin)
                db.session.commit()
                print(f"✅ Admin account created: {admin_email}")
            else:
                print(f"ℹ️  Admin account already exists: {admin_email}")
        else:
            print("⚠️  ADMIN_EMAIL and ADMIN_PASSWORD not set in environment variables")
            print("⚠️  Admin account will not be created automatically")
    except Exception as e:
        print(f"⚠️ Database initialization error: {e}")
        import traceback
        traceback.print_exc()

# Before running the app
if os.environ.get('RENDER'):
    # Render uses ephemeral storage - uploads won't persist!
    print("⚠️ WARNING: Uploads will be lost on restart!")
    print("💡 Consider using Cloudinary or AWS S3 for production")

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
# ========== APPLICATION ENTRY POINT ==========

def create_app():
    """Application factory pattern for Render compatibility"""
    return app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    
    # Production settings for Render
    if os.environ.get('RENDER'):
        print("=" * 60)
        print("🚀 Starting Boardify in PRODUCTION mode on Render")
        print("=" * 60)
        db_type = "PostgreSQL" if 'postgresql' in database_url else "SQLite"
        print(f"📊 Database: {db_type}")
        print(f"📧 Email: {'Enabled ✅' if EMAIL_ENABLED else 'Disabled ⚠️'}")
        print(f"🔒 Security: HTTPS, Secure Cookies")
        print(f"🌐 Port: {port}")
        print("=" * 60)
        create_app().run(host="0.0.0.0", port=port, debug=False)
    else:
        # Development settings
        print("=" * 60)
        print("🔧 Starting Boardify in DEVELOPMENT mode")
        print("=" * 60)
        print(f"📊 Database: SQLite (local)")
        print(f"📧 Email: {'Enabled ✅' if EMAIL_ENABLED else 'Disabled ⚠️ (auto-verify users)'}")
        print(f"🌐 Port: {port}")
        print(f"🔑 Admin: {os.environ.get('ADMIN_EMAIL', 'Not configured')}")
        print("=" * 60)
        debug_mode = os.environ.get('FLASK_ENV') == 'development'
        create_app().run(host="0.0.0.0", port=port, debug=debug_mode)