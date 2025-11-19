from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from apscheduler.schedulers.background import BackgroundScheduler
from werkzeug.utils import secure_filename
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer
from math import ceil
from sqlalchemy import or_
from flask_migrate import Migrate
from flask import jsonify
import os
import uuid

# Models
from models import db, User, Property, Booking, Billing, Message as MessageModel, Policy, HelpSupport, PropertyImage, Review

# Flask setup
app = Flask(__name__)
app.secret_key = "supersecretkey"

# Database setup
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.join(BASE_DIR, 'instance', 'boardify.db')}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_IMAGE_COUNT'] = 10
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5MB
app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'static', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

# Email configuration - FIXED
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False
app.config['MAIL_USERNAME'] = 'lebrontan2004@gmail.com'
app.config['MAIL_PASSWORD'] = 'ujwcaixyxjgdkixd'  # ← NEW PASSWORD (no spaces)
app.config['MAIL_DEFAULT_SENDER'] = 'lebrontan2004@gmail.com'
app.config['SECURITY_PASSWORD_SALT'] = 'boardify-secret-2024'

mail = Mail(app)
ts = URLSafeTimedSerializer(app.config['SECRET_KEY'])

def send_verification_email(user):
    """Send verification email to user"""
    try:
        token = ts.dumps(user.email, salt='email-verify')
        verification_url = url_for('verify_email', token=token, _external=True)
        
        msg = Message(
            'Verify Your Email - Boardify',
            recipients=[user.email],
            sender=app.config['MAIL_DEFAULT_SENDER'],
            html=f'''
            <h2>Welcome to Boardify!</h2>
            <p>Please verify your email address by clicking the link below:</p>
            <a href="{verification_url}" style="padding: 10px 20px; background-color: #007bff; color: white; text-decoration: none; border-radius: 5px;">Verify Email</a>
            <p>This link will expire in 24 hours.</p>
            <p>If you didn't create an account, please ignore this email.</p>
            '''
        )
        
        mail.send(msg)
        user.verification_token = token
        db.session.commit()
        print(f"✅ Verification email sent to {user.email}")
        return True
    except Exception as e:
        print(f"❌ Error sending email to {user.email}: {str(e)}")
        return False
    
def verify_token(token, expiration=86400):  # 24 hours
    """Verify the token and return email if valid"""
    try:
        email = ts.loads(token, salt='email-verify', max_age=expiration)
        return email
    except:
        return None

# File check
def allowed_file(file):
    if not hasattr(file, 'filename'):
        return False
    filename = file.filename
    if not filename or '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return False
    # Check file size
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size > app.config['MAX_CONTENT_LENGTH']:
        return False
    return True


def calculate_total_bill(property, start_date, end_date):
    from datetime import datetime

    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    total_days = (end - start).days + 1  # include last day

    if total_days <= 0:
        raise ValueError("End date must be after start date.")

    total_bill = property.price * total_days  # use property.price instead of monthly_rate
    return total_bill, total_days


def calculate_final_amount(amount, status, due_date, payment_date=None):
    today = date.today()
    discount = 0
    penalty = 0
    if status.lower() == 'paid' and payment_date and payment_date <= due_date:
        discount = amount * 0.05
    elif status.lower() == 'unpaid' and due_date < today:
        penalty = amount * 0.1
    return amount - discount + penalty, discount, penalty

MAX_SLOTS = 9  # maximum tenants per property


# Init DB
db.init_app(app)
migrate = Migrate(app, db)

# Login setup
login_manager = LoginManager(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# UNCOMMENT THIS AND ADD THE MISSING FIELD:
with app.app_context():
    from werkzeug.security import generate_password_hash
    admin_email = "admin@example.com"
    admin_password = "admin123"
    admin = User.query.filter_by(email=admin_email).first()
    if not admin:
        admin = User(
            name="Admin",
            email=admin_email,
            password_hash=generate_password_hash(admin_password, method="pbkdf2:sha256"),
            role="admin",
            is_verified=True,
            is_approved_by_admin=True,  # ← ADD THIS LINE
            gender="Prefer not to say",
            birthdate=date(1990, 1, 1)
        )
        db.session.add(admin)
        db.session.commit()
        print("Admin account created successfully!")


    
def get_recent_messages(user_id, limit=3):
    return (
        MessageModel.query  # Change Message to MessageModel
        .filter((MessageModel.sender_id == user_id) | (MessageModel.receiver_id == user_id))
        .order_by(MessageModel.timestamp.desc())
        .limit(limit)
        .all()
    )


# Decorator to require verified landlord status
def verified_landlord_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash("Please login first.", "warning")
            return redirect(url_for('login'))
        
        # Check if user is a landlord
        if current_user.role != 'landlord':
            return f(*args, **kwargs)  # Not a landlord, proceed normally
        
        # Check if landlord is verified by admin
        if not getattr(current_user, 'is_approved_by_admin', False):
            flash('⚠️ Your account is pending admin verification. You cannot access this feature until an admin approves your license document.', 'warning')
            return redirect(url_for('dashboard'))
        
        return f(*args, **kwargs)
    return decorated_function
# --- Check & Apply Penalties for Late Payments ---
def apply_penalties():
    today = date.today()
    unpaid_bills = Billing.query.filter_by(status='unpaid').all()

    for bill in unpaid_bills:
        if bill.due_date and today > bill.due_date:
            days_late = (today - bill.due_date).days
            bill.penalty = days_late * 20  # ₱20 per day late
    db.session.commit()
    print("✅ Penalties updated.")

# --- Apply Discounts for Early Payments ---
def apply_discounts():
    paid_bills = Billing.query.filter_by(status='paid').all()

    for bill in paid_bills:
        if bill.due_date and bill.payment_method and bill.discount == 0:
            bill.discount = bill.amount * 0.05  # 5% discount
    db.session.commit()
    print("💰 Discounts applied.")

# --- Send Monthly SMS Reminders ---
def send_monthly_sms():
    # (We'll connect Twilio later if you want SMS for real)
    unpaid_bills = Billing.query.filter_by(status='unpaid').all()
    for bill in unpaid_bills:
        if not bill.sms_sent:
            print(f"📱 Sending reminder to Tenant {bill.tenant_id}: Please pay your bill for Property {bill.property_id}.")
            bill.sms_sent = True
    db.session.commit()
    print("📆 Monthly reminders sent.")



# ----------------- Helpers -----------------
# A decorator to require login for certain routes
def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("Please login first.", "warning")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ----------------- Routes -----------------
# Home route, redirects to dashboard if logged in, else to login page
# Home page route
@app.route('/')
def home():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))
@app.route('/debug-email')
def debug_email():
    """Test email sending"""
    try:
        msg = Message(
            subject='Test Email from Boardify',
            recipients=['your-actual-email@gmail.com'],  # Use your REAL email here
            body='This is a test email from your Flask app!'
        )
        mail.send(msg)
        return "✅ Email sent successfully! Check your inbox and spam folder."
    except Exception as e:
        return f"❌ Email failed: {str(e)}"
# ---------- Register Route ----------
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        # Check if terms checkbox is checked
        if not request.form.get('terms'):
            flash("You must agree to the terms and conditions to register.", "danger")
            return redirect(url_for('register'))

        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        role = request.form['role']
        gender = request.form['gender']
        birthdate_str = request.form['birthdate']

        
            

        # Check if email already exists
        if User.query.filter_by(email=email).first():
            flash("Email already registered.", "danger")
            return redirect(url_for('register'))

        # Convert birthdate string to Date object and validate age
        try:
            birthdate = datetime.strptime(birthdate_str, '%Y-%m-%d').date()
            
            # Age validation (at least 18 years old)
            today = date.today()
            age = today.year - birthdate.year - ((today.month, today.day) < (birthdate.month, birthdate.day))
            if age < 18:
                flash("You must be at least 18 years old to register.", "danger")
                return redirect(url_for('register'))
                
        except ValueError:
            flash("Invalid birthdate format.", "danger")
            return redirect(url_for('register'))

        # Handle file upload for landlords
        license_file = request.files.get('permit')
        filename = None
        if license_file and role == 'landlord':
            # secure and unique filename
            original_filename = secure_filename(license_file.filename)
            filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{original_filename}"
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            license_file.save(save_path)

        # Create user with new fields
        new_user = User(
            name=name,
            email=email,
            password_hash=generate_password_hash(password),
            role=role,
            gender=gender,
            birthdate=birthdate,
            license_image=filename,  # only for landlords
            is_verified=False  # Start as unverified
        )
        db.session.add(new_user)
        db.session.commit()

        
        # Send verification email
        if send_verification_email(new_user):
            flash("Registration successful! Please check your email to verify your account before logging in.", "success")
        else:
            flash("Registration successful but we couldn't send verification email. Please contact support.", "warning")

        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/verify-email/<token>')
def verify_email(token):
    email = verify_token(token)
    
    if email is None:
        flash("The verification link is invalid or has expired.", "danger")
        return redirect(url_for('login'))
    
    user = User.query.filter_by(email=email).first()
    
    if user is None:
        flash("User not found.", "danger")
        return redirect(url_for('login'))
    
    if user.is_verified:
        flash("Account already verified. Please login.", "info")
        return redirect(url_for('login'))
    
    # Mark user as verified and clear token
    user.is_verified = True
    user.verification_token = None
    db.session.commit()
    
    flash("Email verified successfully! You can now login to your account.", "success")
    return redirect(url_for('login'))

@app.route('/test-email-exact')
def test_email_exact():
    """Test email with exact configuration"""
    try:
        print("=== Testing Email Configuration ===")
        print(f"Username: {app.config['MAIL_USERNAME']}")
        print(f"Password length: {len(app.config['MAIL_PASSWORD'])}")
        print(f"Server: {app.config['MAIL_SERVER']}:{app.config['MAIL_PORT']}")
        
        msg = Message(
            subject='EXACT TEST - Boardify',
            recipients=[app.config['MAIL_USERNAME']],  # Send to yourself
            body='This is an exact test of your email configuration.'
        )
        mail.send(msg)
        return "✅ Email sent! Check your inbox."
    except Exception as e:
        return f"❌ Exact error: {str(e)}"
    
    

@app.route('/debug-email-exact')
def debug_email_exact():
    """See the exact email error with full details"""
    try:
        print("=== EMAIL DEBUG INFO ===")
        print(f"MAIL_USERNAME: {app.config['MAIL_USERNAME']}")
        print(f"MAIL_PASSWORD: {app.config['MAIL_PASSWORD'][:4]}...")  # Show first 4 chars only
        print(f"MAIL_SERVER: {app.config['MAIL_SERVER']}")
        print(f"MAIL_PORT: {app.config['MAIL_PORT']}")
        
        # Test with a simple email
        msg = Message(
            subject='TEST - Boardify Email',
            recipients=[app.config['MAIL_USERNAME']],  # Send to yourself
            body='This is a test email from your Flask app.'
        )
        mail.send(msg)
        return "✅ Email sent successfully! Check your inbox."
        
    except Exception as e:
        error_msg = f"""
        ❌ EMAIL FAILED WITH DETAILS:
        
        Error: {str(e)}
        
        Your Configuration:
        - Email: {app.config['MAIL_USERNAME']}
        - Password: {app.config['MAIL_PASSWORD'][:4]}... (showing first 4 chars)
        - Server: {app.config['MAIL_SERVER']}:{app.config['MAIL_PORT']}
        
        Common Issues:
        1. Wrong App Password (not 16 characters)
        2. 2FA not enabled
        3. Email doesn't match App Password account
        4. App Password has spaces in wrong places
        """
        return error_msg

@app.route('/debug_property/<int:property_id>')
def debug_property(property_id):
    property = Property.query.get_or_404(property_id)
    
    # Show all attributes of the property
    attributes = [attr for attr in dir(property) if not attr.startswith('_')]
    
    return f"""
    <h1>Property Debug Info</h1>
    <p>Property: {property.title}</p>
    <p>All attributes: {attributes}</p>
    <p>Has slots_available: {hasattr(property, 'slots_available')}</p>
    <p>Has total_slots: {hasattr(property, 'total_slots')}</p>
    <p>Has max_tenants: {hasattr(property, 'max_tenants')}</p>
    <p>Has capacity: {hasattr(property, 'capacity')}</p>
    """

# ADD THE MISSING ROUTE HERE:
@app.route('/property_detail/<int:property_id>', methods=['GET'])
def property_detail(property_id):
    property = Property.query.get_or_404(property_id)

    # Tenant's booking, if logged in
    user_booking = None
    user_review = None
    can_review = False
    
    if 'user_id' in session and session.get('user_role') == 'tenant':
        user_id = session['user_id']
        user_booking = Booking.query.filter_by(
            property_id=property.id,
            tenant_id=user_id
        ).all()
        
        # Check if user has reviewed this property
        user_review = Review.query.filter_by(
            property_id=property_id,
            tenant_id=user_id
        ).first()
        
        # User can review if they have an APPROVED booking (during or after stay)
        can_review = Booking.query.filter(
            Booking.property_id == property_id,
            Booking.tenant_id == user_id,
            Booking.status == 'approved'
        ).first() is not None and not user_review

    # FIXED: Calculate actual available slots based on approved bookings
    total_slots = property.slots if property.slots is not None else 10
    approved_bookings_count = sum(1 for booking in property.bookings if booking.status == 'approved')
    slots_left = max(0, total_slots - approved_bookings_count)

    # Get all reviews for this property with tenant info
    reviews = Review.query.filter_by(property_id=property_id).join(User).order_by(Review.created_at.desc()).all()
    
    # Calculate average rating
    avg_rating = 0
    if reviews:
        avg_rating = sum(review.rating for review in reviews) / len(reviews)

    # Prepare image URLs for slider
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
@app.route('/landlord/approved_bookings')
@login_required
@verified_landlord_required 
def approved_bookings():
    user = User.query.get(session.get('user_id'))

    if not user or user.role != 'landlord':
        flash("Access denied. You must be a landlord to view this page.", "danger")
        return redirect(url_for('dashboard'))

    # Get all properties owned by this landlord
    properties = Property.query.filter_by(landlord_id=user.id).all()
    property_ids = [p.id for p in properties]

    # Fetch all pending bookings for landlord’s properties
    bookings = Booking.query.filter(
        Booking.property_id.in_(property_ids),
        Booking.status == 'pending'
    ).all()

    # Render the correct template
    return render_template('approved_bookings.html', bookings=bookings, user=user)

@app.route('/upload_trend', methods=['POST'])
@login_required
def upload_trend():
    if 'file' not in request.files:
        flash("No file part", "danger")
        return redirect(url_for('dashboard'))

    file = request.files['file']
    if file.filename == '':
        flash("No selected file", "danger")
        return redirect(url_for('dashboard'))

    # Check allowed file type and size
    if not allowed_file(file):
        flash("Invalid file type or size exceeds 5MB!", "danger")
        return redirect(url_for('dashboard'))

    # Check existing trend images for the user (optional, if you want a max limit)
    user_trend_count = len(os.listdir(app.config['UPLOAD_FOLDER']))
    if user_trend_count >= app.config['MAX_IMAGE_COUNT']:
        flash(f"Maximum {app.config['MAX_IMAGE_COUNT']} images allowed!", "danger")
        return redirect(url_for('dashboard'))

    # Save the file securely
    filename = secure_filename(file.filename)
    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
    flash("Trend image uploaded successfully!", "success")

    return redirect(url_for('dashboard'))

# Add this route to check
@app.route('/check-user/<email>')
def check_user(email):
    user = User.query.filter_by(email=email).first()
    if user:
        return f"""
        User: {user.name}<br>
        Email: {user.email}<br>
        Verified: {user.is_verified}<br>
        Token: {user.verification_token}
        """
    return "User not found"
@app.route('/reject_booking/<int:booking_id>', methods=['POST'])
@login_required
def reject_booking(booking_id):
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
@app.route('/pending_bookings')
@login_required
@verified_landlord_required
def pending_bookings():
    user = User.query.get(session['user_id'])
    if user.role != 'landlord':
        flash("Access denied.", "danger")
        return redirect(url_for('dashboard'))
    
    # Get all properties owned by this landlord
    properties = Property.query.filter_by(landlord_id=user.id).all()
    property_ids = [p.id for p in properties]
    
    # Fetch pending bookings for landlord's properties
    bookings = Booking.query.filter(
        Booking.property_id.in_(property_ids),
        Booking.status == 'pending'
    ).all()
    
    return render_template('pending_bookings.html', bookings=bookings, user=user)


@app.route('/delete-user/<email>')
def delete_user(email):
    """Delete a user by email - Enhanced to handle all related data"""
    user = User.query.filter_by(email=email).first()
    
    if not user:
        return f"❌ User '{email}' not found."
    
    try:
        # Store info before deletion
        user_name = user.name
        user_role = user.role
        user_id = user.id
        
        print(f"=== DELETING USER: {user_name} ({user_role}) ===")
        
        # === DELETE LANDLORD DATA ===
        if user_role == 'landlord':
            properties = Property.query.filter_by(landlord_id=user_id).all()
            print(f"Found {len(properties)} properties to delete")
            
            for prop in properties:
                print(f"Deleting property: {prop.title}")
                
                # Delete property images (database records)
                property_images = PropertyImage.query.filter_by(property_id=prop.id).all()
                for img in property_images:
                    # Delete physical file
                    file_path = os.path.join(app.config['UPLOAD_FOLDER'], img.filename)
                    if os.path.exists(file_path):
                        try:
                            os.remove(file_path)
                            print(f"  Deleted image file: {img.filename}")
                        except Exception as e:
                            print(f"  Error deleting image file: {e}")
                    db.session.delete(img)
                
                # Delete main property image file
                if prop.image:
                    main_image_path = os.path.join(app.config['UPLOAD_FOLDER'], prop.image)
                    if os.path.exists(main_image_path):
                        try:
                            os.remove(main_image_path)
                            print(f"  Deleted main image: {prop.image}")
                        except Exception as e:
                            print(f"  Error deleting main image: {e}")
                
                # Delete associated data for this property
                bookings_deleted = Booking.query.filter_by(property_id=prop.id).delete()
                bills_deleted = Billing.query.filter_by(property_id=prop.id).delete()
                reviews_deleted = Review.query.filter_by(property_id=prop.id).delete()
                
                print(f"  Deleted {bookings_deleted} bookings, {bills_deleted} bills, {reviews_deleted} reviews")
                
                # Delete the property itself
                db.session.delete(prop)
        
        # === DELETE TENANT DATA ===
        if user_role == 'tenant':
            bookings_deleted = Booking.query.filter_by(tenant_id=user_id).delete()
            bills_deleted = Billing.query.filter_by(tenant_id=user_id).delete()
            reviews_deleted = Review.query.filter_by(tenant_id=user_id).delete()
            print(f"Deleted {bookings_deleted} bookings, {bills_deleted} bills, {reviews_deleted} reviews")
        
        # === DELETE COMMON DATA (for all users) ===
        # Delete messages
        messages_deleted = MessageModel.query.filter(
            (MessageModel.sender_id == user_id) | (MessageModel.receiver_id == user_id)
        ).delete()
        print(f"Deleted {messages_deleted} messages")
        
        # Delete help tickets
        tickets_deleted = HelpSupport.query.filter_by(user_id=user_id).delete()
        print(f"Deleted {tickets_deleted} help tickets")
        
        # Delete profile picture file
        if hasattr(user, 'profile_pic') and user.profile_pic:
            profile_pic_path = os.path.join(app.config['UPLOAD_FOLDER'], user.profile_pic)
            if os.path.exists(profile_pic_path):
                try:
                    os.remove(profile_pic_path)
                    print(f"Deleted profile picture: {user.profile_pic}")
                except Exception as e:
                    print(f"Error deleting profile pic: {e}")
        
        # Delete license image file (for landlords)
        if user.license_image:
            license_path = os.path.join(app.config['UPLOAD_FOLDER'], user.license_image)
            if os.path.exists(license_path):
                try:
                    os.remove(license_path)
                    print(f"Deleted license image: {user.license_image}")
                except Exception as e:
                    print(f"Error deleting license: {e}")
        
        # Finally, delete the user
        db.session.delete(user)
        db.session.commit()
        
        print(f"=== USER {user_name} DELETED SUCCESSFULLY ===")
        
        return f"""
        <h2>✅ User Deleted Successfully!</h2>
        <p><strong>Name:</strong> {user_name}</p>
        <p><strong>Email:</strong> {email}</p>
        <p><strong>Role:</strong> {user_role}</p>
        <br>
        <a href="/register" style="padding: 10px 20px; background: #007bff; color: white; text-decoration: none; border-radius: 5px;">Register Again</a>
        <a href="/login" style="padding: 10px 20px; background: #28a745; color: white; text-decoration: none; border-radius: 5px; margin-left: 10px;">Login</a>
        """
        
    except Exception as e:
        db.session.rollback()
        import traceback
        error_trace = traceback.format_exc()
        print(f"=== ERROR DELETING USER ===")
        print(error_trace)
        return f"""
        <h2>❌ Error Deleting User</h2>
        <p><strong>Error:</strong> {str(e)}</p>
        <pre style="background: #f5f5f5; padding: 15px; border-radius: 5px; overflow-x: auto;">{error_trace}</pre>
        <br>
        <a href="javascript:history.back()" style="padding: 10px 20px; background: #dc3545; color: white; text-decoration: none; border-radius: 5px;">Go Back</a>
        """


@app.route('/edit-property/<int:property_id>', methods=['GET', 'POST'])
@login_required
def edit_property(property_id):
    """Edit property - landlords can only edit their own properties"""
    user_id = session.get('user_id')
    user = User.query.get(user_id)
    
    # Get the property
    property_obj = Property.query.get_or_404(property_id)
    
    # Check if user is the owner
    if user.role != 'landlord' or property_obj.landlord_id != user_id:
        flash('You do not have permission to edit this property.', 'danger')
        return redirect(url_for('viewproperties'))
    
    if request.method == 'POST':
        # Check if this is an AJAX image deletion request
        if request.form.get('action') == 'delete_image':
            return delete_image()
        
        try:
            # Update property details
            property_obj.title = request.form.get('title')
            property_obj.description = request.form.get('description')
            property_obj.location = request.form.get('location')
            property_obj.price = float(request.form.get('price'))
            property_obj.total_slots = int(request.form.get('total_slots'))
            property_obj.gender_preference = request.form.get('gender_preference')
            property_obj.status = request.form.get('status', 'available')
            
            # Handle multiple new image uploads
            if 'images' in request.files:
                files = request.files.getlist('images')
                
                # Check total image count (existing + new)
                existing_count = PropertyImage.query.filter_by(property_id=property_id).count()
                if existing_count + len(files) > app.config['MAX_IMAGE_COUNT']:
                    flash(f"Maximum {app.config['MAX_IMAGE_COUNT']} images allowed per property.", "danger")
                    return redirect(url_for('edit_property', property_id=property_id))
                
                for idx, file in enumerate(files):
                    if file and file.filename != '' and allowed_file(file):
                        # Save new image
                        filename = secure_filename(file.filename)
                        unique_filename = f"{uuid.uuid4()}_{filename}"
                        file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
                        file.save(file_path)
                        
                        # If this is the first image and property has no main image, set it
                        if idx == 0 and not property_obj.image:
                            property_obj.image = unique_filename
                        
                        # Add to PropertyImage table
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
            print(f"Error in edit_property: {str(e)}")
    
    # GET request - fetch property images
    property_images = PropertyImage.query.filter_by(property_id=property_id).all()
    
    return render_template('edit_property.html', 
                         property=property_obj, 
                         user=user,
                         images=property_images)



# REPLACE your existing delete_property route with this updated version
@app.route('/delete-property/<int:property_id>', methods=['POST'])
@login_required
def delete_property(property_id):
    """Delete property - landlords can only delete their own properties"""
    user_id = session.get('user_id')
    user = User.query.get(user_id)
    
    # Get the property
    property_obj = Property.query.get_or_404(property_id)
    
    # Check if user is the owner
    if user.role != 'landlord' or property_obj.landlord_id != user_id:
        return jsonify({'success': False, 'message': 'You do not have permission to delete this property.'}), 403
    
    try:
        # Delete all associated images (both files and database records)
        property_images = PropertyImage.query.filter_by(property_id=property_id).all()
        for img in property_images:
            # Delete physical file
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], img.filename)
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception as e:
                    print(f"Error deleting image file {img.filename}: {e}")
            
            # Delete database record
            db.session.delete(img)
        
        # Delete main property image if exists
        if property_obj.image:
            main_image_path = os.path.join(app.config['UPLOAD_FOLDER'], property_obj.image)
            if os.path.exists(main_image_path):
                try:
                    os.remove(main_image_path)
                except Exception as e:
                    print(f"Error deleting main image: {e}")
        
        # Delete associated bookings
        Booking.query.filter_by(property_id=property_id).delete()
        
        # Delete associated bills
        Billing.query.filter_by(property_id=property_id).delete()
        
        # Delete associated reviews
        Review.query.filter_by(property_id=property_id).delete()
        
        # Delete the property
        db.session.delete(property_obj)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Property deleted successfully'})
        
    except Exception as e:
        db.session.rollback()
        print(f"Error deleting property: {str(e)}")
        return jsonify({'success': False, 'message': f'Error deleting property: {str(e)}'}), 500


@app.route('/delete-image', methods=['POST'])
@login_required
def delete_image():
    """Delete a property image via AJAX"""
    user_id = session.get('user_id')
    user = User.query.get(user_id)
    
    if user.role != 'landlord':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    try:
        image_id = request.form.get('image_id')
        action = request.form.get('action')
        
        if action != 'delete_image' or not image_id:
            return jsonify({'success': False, 'message': 'Invalid request'}), 400
        
        # Get the image
        image = PropertyImage.query.get(image_id)
        
        if not image:
            return jsonify({'success': False, 'message': 'Image not found'}), 404
        
        # Check if user owns this property
        property_obj = Property.query.get(image.property_id)
        if not property_obj or property_obj.landlord_id != user_id:
            return jsonify({'success': False, 'message': 'Unauthorized'}), 403
        
        # Delete the physical file
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], image.filename)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as e:
                print(f"Error deleting file: {e}")
        
        # If this is the main property image, update it
        if property_obj.image == image.filename:
            # Set the main image to the next available image or None
            remaining_images = PropertyImage.query.filter(
                PropertyImage.property_id == property_obj.id,
                PropertyImage.id != image.id
            ).first()
            
            if remaining_images:
                property_obj.image = remaining_images.filename
            else:
                property_obj.image = None
        
        # Delete from database
        db.session.delete(image)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Image deleted successfully'})
        
    except Exception as e:
        db.session.rollback()
        print(f"Error deleting image: {str(e)}")
        return jsonify({'success': False, 'message': f'Error: {str(e)}'}), 500

@app.route('/landlord/booking_action/<int:booking_id>/<action>', methods=['POST'])
@login_required
def booking_action(booking_id, action):
    user = User.query.get(session['user_id'])
    
    if user.role != 'landlord':
        flash("Access denied.", "danger")
        return redirect(url_for('dashboard'))

    booking = Booking.query.get_or_404(booking_id)

    # Ensure this landlord owns the property
    if booking.property.landlord_id != user.id:
        flash("You cannot modify this booking.", "danger")
        return redirect(url_for('pending_bookings'))

    if action == 'approve':
        booking.status = 'approved'
        booking.property.status = 'booked'

        # Create billing if none exists
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



@app.route("/inbox")
@login_required
def inbox():
    my_id = session["user_id"]

    chat_partners = (
        db.session.query(User)
        .join(MessageModel, or_(MessageModel.sender_id == User.id, MessageModel.receiver_id == User.id))  # Change here
        .filter(or_(MessageModel.sender_id == my_id, MessageModel.receiver_id == my_id))  # Change here
        .filter(User.id != my_id)
        .distinct()
        .all()
    )

    return render_template("inbox.html", partners=chat_partners)

# --- Add Review Route ---
@app.route('/add_review/<int:property_id>', methods=['POST'])
@login_required
def add_review(property_id):
    user = User.query.get(session['user_id'])
    property = Property.query.get_or_404(property_id)
    
    # FIXED: User can review if they have an APPROVED booking (during or after stay)
    has_approved_booking = Booking.query.filter(
        Booking.property_id == property_id,
        Booking.tenant_id == user.id,
        Booking.status == 'approved'
        # Removed the end_date check
    ).first()
    
    if not has_approved_booking:
        flash("You can only review properties you have an approved booking for.", "warning")
        return redirect(url_for('property_detail', property_id=property_id))
    
    # Check if user already reviewed this property
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


@app.route('/debug-email-full')
def debug_email_full():
    """Comprehensive email debug"""
    try:
        print("=== FULL EMAIL DEBUG ===")
        print(f"MAIL_USERNAME: {app.config['MAIL_USERNAME']}")
        print(f"MAIL_PASSWORD: {app.config['MAIL_PASSWORD']}")
        print(f"MAIL_SERVER: {app.config['MAIL_SERVER']}")
        print(f"MAIL_PORT: {app.config['MAIL_PORT']}")
        print(f"MAIL_USE_TLS: {app.config['MAIL_USE_TLS']}")
        
        # Test sending to YOURSELF
        msg = Message(
            subject='FINAL TEST - Boardify Email',
            recipients=['lebrontan2004@gmail.com'],  # Send to yourself
            body='This is the final test email. If you get this, email is working!',
            sender=app.config['MAIL_DEFAULT_SENDER']
        )
        
        mail.send(msg)
        return """
        <h2>✅ Email sent successfully!</h2>
        <p>Check your inbox at <strong>lebrontan2004@gmail.com</strong></p>
        <p>Refresh your inbox and check spam folder.</p>
        """
        
    except Exception as e:
        return f"""
        <h2>❌ Email Failed Completely</h2>
        <p><strong>Error:</strong> {str(e)}</p>
        <h3>Your Current Configuration:</h3>
        <ul>
            <li>Username: {app.config['MAIL_USERNAME']}</li>
            <li>Password: {app.config['MAIL_PASSWORD']} (length: {len(app.config['MAIL_PASSWORD'])})</li>
            <li>Server: {app.config['MAIL_SERVER']}:{app.config['MAIL_PORT']}</li>
        </ul>
        <h3>Possible Issues:</h3>
        <ol>
            <li>App password is incorrect</li>
            <li>2FA not enabled on Gmail</li>
            <li>Google blocking sign-in attempts</li>
            <li>Need to allow less secure apps (temporarily)</li>
        </ol>
        """
@app.route('/test-new-app-password')
def test_new_app_password():
    try:
        msg = Message(
            subject='Boardify - New App Password Test',
            recipients=['lebrontan2004@gmail.com'],
            body='If you receive this, your NEW app password is working! 🎉'
        )
        mail.send(msg)
        return """
        <h2>✅ Email sent with NEW app password!</h2>
        <p>Check your inbox at <strong>lebrontan2004@gmail.com</strong></p>
        <p>Refresh and check spam folder if needed.</p>
        """
    except Exception as e:
        return f"""
        <h2>❌ Still failing with new password</h2>
        <p><strong>Error:</strong> {str(e)}</p>
        <p>Try allowing less secure apps as a temporary solution.</p>
        """

# --- Edit Review Route ---
@app.route('/edit_review/<int:review_id>', methods=['GET', 'POST'])
@login_required
def edit_review(review_id):
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

# --- Delete Review Route ---
@app.route('/delete_review/<int:review_id>', methods=['POST'])
@login_required
def delete_review(review_id):
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

# --- Safe way to create Review table (run once) ---
@app.route('/create_review_table')
def create_review_table():
    try:
        # Create only the Review table if it doesn't exist
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        
        if 'review' not in inspector.get_table_names():
            Review.__table__.create(db.engine)
            return "✅ Review table created successfully! You can now remove this route."
        else:
            return "✅ Review table already exists! You can remove this route."
    except Exception as e:
        return f"❌ Error: {str(e)}"
    

@app.route('/fix-db-now')
def fix_db_now():
    """Force fix the database"""
    try:
        # Drop and recreate all tables
        db.drop_all()
        db.create_all()
        
        # Create admin user
        from werkzeug.security import generate_password_hash
        admin = User(
            name="Admin",
            email="admin@example.com",
            password_hash=generate_password_hash("admin123", method="pbkdf2:sha256"),
            role="admin",
            is_verified=True,
            is_approved_by_admin=True,
            gender="Prefer not to say",
            birthdate=date(1990, 1, 1)
        )
        db.session.add(admin)
        db.session.commit()
        
        return "✅ Database completely reset with correct schema!"
    except Exception as e:
        return f"Error: {str(e)}"

@app.route("/messages/<int:user_id>", methods=["GET", "POST"])
@login_required
def messages(user_id):
    my_id = session["user_id"]
    other = User.query.get_or_404(user_id)

    if request.method == "POST":
        content = request.form.get("content", "").strip()
        if content:
            db.session.add(MessageModel(sender_id=my_id, receiver_id=other.id, content=content))  # Change here
            db.session.commit()
            flash("Message sent!", "success")
        else:
            flash("Message cannot be empty.", "warning")
        return redirect(url_for("messages", user_id=other.id))

    chat = (
        MessageModel.query  # Change here
        .filter(
            or_(
                (MessageModel.sender_id == my_id) & (MessageModel.receiver_id == other.id),
                (MessageModel.sender_id == other.id) & (MessageModel.receiver_id == my_id),
            )
        )
        .order_by(MessageModel.timestamp.asc())  # Change here
        .all()
    )

    return render_template("messages.html", chat=chat, other=other)

@app.route('/export-data')
@login_required
def export_data():
    """Simple data export endpoint"""
    flash('Data export feature is coming soon!', 'info')
    return redirect(url_for('profile'))



@app.route('/send_message/<int:receiver_id>', methods=['POST'])
def send_message(receiver_id):
    if 'user_id' not in session:
        flash("Please log in first.")
        return redirect(url_for('login'))

    sender_id = session['user_id']
    content = request.form.get('content')

    if content.strip() == "":
        flash("Message cannot be empty.")
        return redirect(url_for('messages', user_id=receiver_id))

    new_message = MessageModel(sender_id=sender_id, receiver_id=receiver_id, content=content)  # Change here
    db.session.add(new_message)
    db.session.commit()

    return redirect(url_for('messages', user_id=receiver_id))

@app.route("/users")
@login_required
def users():
    all_users = User.query.all()
    return render_template("users.html", users=all_users)


@app.route('/process_payment', methods=['POST'])
def process_payment():
    method = request.form.get('payment_method')
    # handle different payment methods here
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




@app.route('/confirm_payment/<int:bill_id>', methods=['POST'])
@login_required
def confirm_payment(bill_id):
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

    # Total based on months booked
    total_amount = (bill.amount * (bill.months or 1)) + (bill.penalty or 0) - (bill.discount or 0)

    # Admin commission 5% of total
    bill.admin_commission = total_amount * 0.05

    bill.status = 'paid'
    bill.payment_method = payment_method

    db.session.commit()

    flash(f"Bill {bill.id} has been paid! Total: ₱{total_amount:.2f}, Admin Commission: ₱{bill.admin_commission:.2f}", "success")
    return redirect(url_for('billing'))



# Admin dashboard route showing total commissions
@app.route('/admin/commissions')
@login_required
def admin_commissions():
    user = User.query.get(session['user_id'])
    if user.role != 'admin':
        flash("You are not allowed to access this page.", "danger")
        return redirect(url_for('dashboard'))

    # Get all paid bills with commission
    paid_bills = Billing.query.filter_by(status='paid').all()
    total_commission = sum(bill.admin_commission or 0 for bill in paid_bills)
    
    # Calculate pending commission
    unpaid_bills = Billing.query.filter_by(status='unpaid').all()
    pending_commission = sum(bill.amount * 0.05 for bill in unpaid_bills)
    
    # Get additional stats
    properties_count = Property.query.count()
    tenants_count = User.query.filter_by(role='tenant').count()

    return render_template('admin_commissions.html', 
                         total_commission=total_commission,
                         pending_commission=pending_commission,
                         properties_count=properties_count,
                         tenants_count=tenants_count,
                         bills=paid_bills,
                         user=user)


# Tenant's view of their own bookings
@app.route('/my_bookings')
@login_required
def my_bookings_tenant():
    user = User.query.get(session['user_id'])

    # Only allow tenants to access this page
    if not user or user.role != 'tenant':
        flash("Access denied. You must be a tenant to view this page.", "danger")
        return redirect(url_for('dashboard'))

    # Fetch all bookings for this tenant
    bookings = Booking.query.filter_by(tenant_id=user.id).all()

    return render_template('my_bookings_tenant.html', bookings=bookings, user=user)


@app.route('/pay_bill/<int:bill_id>', methods=['POST'])
@login_required
def pay_bill(bill_id):
    user = User.query.get(session['user_id'])
    if user.role != 'landlord':
        flash("You are not allowed to perform this action.", "danger")
        return redirect(url_for('billing'))

    bill = Billing.query.get_or_404(bill_id)
    if bill.status == 'paid':
        flash("This bill has already been paid.", "info")
        return redirect(url_for('billing'))

    # Calculate discount or penalty
    today = date.today()
    discount = 0
    penalty = 0

    if bill.due_date:
        if today <= bill.due_date:
            discount = bill.amount * 0.05  # 5% early payment discount
        else:
            days_late = (today - bill.due_date).days
            penalty = days_late * 50  # Example: 50 per day late fee

    final_amount = bill.amount - discount + penalty

    # Update bill
    bill.status = 'paid'
    bill.discount = discount
    bill.penalty = penalty
    bill.payment_date = today
    db.session.commit()

    flash(f"Bill {bill.id} marked as paid! Final amount: ₱{final_amount:.2f}", "success")
    return redirect(url_for('billing'))


@app.route('/monthly_invoice', methods=['GET', 'POST'])
@login_required
def monthly_invoice():
    user = current_user
    if not user:
        flash("Please login first.", "danger")
        return redirect(url_for('login'))

    # Default: show current month
    selected_year = request.args.get('year', date.today().year, type=int)
    selected_month = request.args.get('month', date.today().month, type=int)

    # Filter bills by month
    if user.role == 'landlord':
        bills = Billing.query.join(Property).filter(
            Property.landlord_id == user.id,
            db.extract('year', Billing.due_date) == selected_year,
            db.extract('month', Billing.due_date) == selected_month
        ).all()
    else:  # tenant
        bills = Billing.query.filter(
            Billing.tenant_id == user.id,
            db.extract('year', Billing.due_date) == selected_year,
            db.extract('month', Billing.due_date) == selected_month
        ).all()

    # Calculate total, discounts, penalties
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




@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password_hash, password):
            # Check if email is verified
            if not user.is_verified:
                flash("Please verify your email before logging in. Check your inbox for the verification link.", "warning")
                return redirect(url_for('login'))
                
            login_user(user)  # Flask-Login
            session['user_id'] = user.id
            session['user_role'] = user.role
            session['user_name'] = user.name
            session['user_verified'] = user.is_verified  # Add verification status to session
            flash("Login successful!", "success")
            return redirect(url_for('dashboard'))

        flash("Invalid credentials.", "danger")
        return redirect(url_for('login'))

    return render_template('login.html')

@app.route('/test-verification')
def test_verification():
    """Test verification without real email"""
    # Create a test user
    test_user = User(
        name="Test User",
        email="test@example.com", 
        password_hash="test",
        role="tenant",
        is_verified=False
    )
    db.session.add(test_user)
    db.session.commit()
    
    # Try to send verification
    if send_verification_email(test_user):
        return "✅ Email would be sent! User created with is_verified=False"
    else:
        return "❌ Email failed, but user was created with is_verified=False"

@app.route('/resend-verification', methods=['POST'])
def resend_verification():
    email = request.form.get('email')
    user = User.query.filter_by(email=email).first()
    
    if user:
        if user.is_verified:
            flash("Email is already verified.", "info")
            return redirect(url_for('login'))
        
        if send_verification_email(user):
            flash("Verification email sent! Please check your inbox.", "success")
        else:
            flash("Failed to send verification email. Please try again later.", "danger")
    else:
        flash("Email not found.", "danger")
    
    return redirect(url_for('login'))



@app.route('/test-email-detailed')
def test_email_detailed():
    """Detailed email test with full error reporting"""
    try:
        print("=== Testing Email Configuration ===")
        print(f"Username: {app.config['MAIL_USERNAME']}")
        print(f"Password: {app.config['MAIL_PASSWORD']} (length: {len(app.config['MAIL_PASSWORD'])})")
        print(f"Server: {app.config['MAIL_SERVER']}:{app.config['MAIL_PORT']}")
        
        # Test with a simple message
        msg = Message(
            subject='Boardify - Test Email',
            recipients=[app.config['MAIL_USERNAME']],  # Send to yourself
            body='This is a test email from your Boardify application.',
            sender=app.config['MAIL_DEFAULT_SENDER']
        )
        
        mail.send(msg)
        return """
        <h2>✅ Email sent successfully!</h2>
        <p>Check your inbox and spam folder at <strong>lebrontan2004@gmail.com</strong></p>
        <p>If you don't see it:</p>
        <ol>
            <li>Check your spam folder</li>
            <li>Wait 1-2 minutes</li>
            <li>Verify the app password is correct</li>
        </ol>
        """
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        return f"""
        <h2>❌ Email Failed</h2>
        <p><strong>Error:</strong> {str(e)}</p>
        <p><strong>Full Details:</strong></p>
        <pre>{error_details}</pre>
        
        <h3>Checklist:</h3>
        <ul>
            <li>✅ 2FA enabled on Gmail</li>
            <li>✅ App Password generated (16 characters)</li>
            <li>✅ Using App Password, not regular password</li>
            <li>✅ No spaces in app password</li>
            <li>✅ Correct email: lebrontan2004@gmail.com</li>
        </ul>
        """

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    user = User.query.get(session.get('user_id'))
    if not user:
        flash("User not found.", "danger")
        return redirect(url_for('login'))

    # Handle profile update
    if request.method == 'POST':
        new_name = request.form.get('name')
        if new_name:
            user.name = new_name
            session['user_name'] = new_name  # Update session

        # Handle gender and birthdate
        user.gender = request.form.get('gender')
        birthdate_str = request.form.get('birthdate')
        if birthdate_str:
            try:
                user.birthdate = datetime.strptime(birthdate_str, '%Y-%m-%d').date()
            except ValueError:
                flash("Invalid birthdate format.", "danger")

        # Handle email update with re-verification
        new_email = request.form.get('email')
        if new_email and new_email != user.email:
            # Check if email already exists
            existing_user = User.query.filter_by(email=new_email).first()
            if existing_user and existing_user.id != user.id:
                flash("Email already registered to another account.", "danger")
            else:
                user.email = new_email
                user.is_verified = False  # Require re-verification for new email
                # Send new verification email
                if send_verification_email(user):
                    flash("Email updated! Please verify your new email address.", "warning")
                else:
                    flash("Email updated but verification email failed to send. Please contact support.", "warning")

        # Handle phone and bio if you have these fields
        if hasattr(user, 'phone'):
            user.phone = request.form.get('phone')
        if hasattr(user, 'bio'):
            user.bio = request.form.get('bio')

        # Handle profile picture upload
        file = request.files.get('profile_pic')
        if file and file.filename != '':
            if allowed_file(file):
                filename = secure_filename(file.filename)
                # Add timestamp to make filename unique
                unique_filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
                file.save(file_path)
                user.profile_pic = unique_filename
            else:
                flash("Invalid file type or file too large. Please use PNG, JPG, or JPEG files under 5MB.", "danger")

        # Handle resend verification request
        if request.form.get('resend_verification'):
            if not user.is_verified:
                if send_verification_email(user):
                    flash("Verification email sent! Please check your inbox.", "success")
                else:
                    flash("Failed to send verification email. Please try again later.", "danger")
            else:
                flash("Your email is already verified.", "info")

        db.session.commit()
        flash("Profile updated successfully!", "success")
        return redirect(url_for('profile'))

    # Fetch user-specific data
    if user.role == 'landlord':
        properties = Property.query.filter_by(landlord_id=user.id).all()
        bookings = Booking.query.join(Property).filter(Property.landlord_id == user.id).all()
        bills = Billing.query.join(Property).filter(Property.landlord_id == user.id).all()
    else:
        properties = []
        bookings = Booking.query.filter_by(tenant_id=user.id).all()
        bills = Billing.query.filter_by(tenant_id=user.id).all()

    # Update session with current verification status
    session['user_verified'] = user.is_verified

    # Calculate age for display
    age = None
    if user.birthdate:
        from datetime import date
        today = date.today()
        age = today.year - user.birthdate.year - ((today.month, today.day) < (user.birthdate.month, user.birthdate.day))

    # Render profile
    return render_template(
        'profile.html',
        user=user,
        properties=properties,
        bookings=bookings,
        bills=bills,
        today=date.today(),
        age=age,
        verified=user.is_verified  # Pass verification status to template
    )
 # --- View Policies ---
@app.route('/policies')
@login_required
def policies():
    user = User.query.get(session['user_id'])
    if not user:
        flash("User not found. Please log in again.", "danger")
        return redirect(url_for('login'))

    # Show policies relevant to the logged-in user
    relevant_policies = Policy.query.filter(
        (Policy.applicable_role == user.role) | (Policy.applicable_role == 'all')
    ).all()

    return render_template('policies.html', user=user, policies=relevant_policies)

# --- Add Policy (Landlord/Admin only) ---
@app.route('/add_policy', methods=['GET', 'POST'])
@login_required
def add_policy():
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


@app.route('/bills/<int:user_id>')
def bills_page(user_id):
    # Get the user
    user = User.query.get_or_404(user_id)

    # Fetch bills based on role
    if user.role == 'landlord':
        # Landlord sees all bills for their properties
        bills = Billing.query.join(Property).filter(Property.landlord_id == user.id).all()
    else:  # tenant
        bills = Billing.query.filter_by(tenant_id=user.id).all()

    # Calculate penalties and discounts
    for bill in bills:
        bill.current_penalty = 0
        bill.current_discount = 0

        # Discount if paid before due date
        if bill.status.lower() == 'paid' and bill.due_date and hasattr(bill, 'payment_date'):
            if bill.payment_date <= bill.due_date:
                bill.current_discount = bill.amount * 0.05  # 5% early payment discount

        # Penalty if unpaid and past due date
        elif bill.status.lower() == 'unpaid' and bill.due_date:
            if date.today() > bill.due_date:
                bill.current_penalty = bill.amount * 0.1  # 10% late penalty

    # Render the bills template
    return render_template('bills.html', bills=bills, user=user)

@app.route('/help_support', methods=['GET', 'POST'])
@login_required
def help_support():
    user = User.query.get(session['user_id'])

    if request.method == 'POST':
        subject = request.form.get('subject')
        message = request.form.get('message')

        if not subject or not message:
            flash("All fields are required.", "danger")
        else:
            # Here you can save to DB or send email
            # Example: save to HelpSupport table
            new_ticket = HelpSupport(user_id=user.id, subject=subject, message=message)
            db.session.add(new_ticket)
            db.session.commit()

            flash("Your message has been sent! We'll get back to you soon.", "success")
            return redirect(url_for('dashboard'))

    return render_template('help_support.html', user=user)


@app.route('/support_tickets')
@login_required
def support_tickets():
    user = User.query.get(session['user_id'])

    if user.role != 'admin':
        flash("You are not allowed to view support tickets.", "danger")
        return redirect(url_for('dashboard'))

    tickets = HelpSupport.query.order_by(HelpSupport.timestamp.desc()).all()
    return render_template('support_tickets.html', tickets=tickets, user=user)

@app.route('/my_tickets')
@login_required
def my_tickets():
    user = User.query.get(session['user_id'])
    tickets = HelpSupport.query.filter_by(user_id=user.id).order_by(HelpSupport.timestamp.desc()).all()
    return render_template('my_tickets.html', tickets=tickets, user=user)


@app.route('/admin/help_tickets', methods=['GET', 'POST'])
@login_required
def admin_help_tickets():
    user = User.query.get(session['user_id'])
    
    # Only allow admin to access
    if user.role != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('dashboard'))

    # Handle status updates
    if request.method == 'POST':
        ticket_id = request.form.get('ticket_id')
        new_status = request.form.get('status')
        ticket = HelpSupport.query.get(ticket_id)
        if ticket and new_status in ['pending', 'resolved']:
            ticket.status = new_status
            db.session.commit()
            flash(f"Ticket '{ticket.subject}' updated to {new_status}.", "success")
        return redirect(url_for('admin_help_tickets'))

    # Fetch all tickets
    tickets = HelpSupport.query.order_by(HelpSupport.timestamp.desc()).all()
    return render_template('admin_help_tickets.html', tickets=tickets, user=user)

@app.route('/admin/help_support')
@login_required
def admin_help_support():
    user = User.query.get(session['user_id'])
    if user.role != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('dashboard'))

    # Get all tickets ordered by newest first
    tickets = HelpSupport.query.order_by(HelpSupport.timestamp.desc()).all()
    return render_template('admin_help_support.html', tickets=tickets)






@app.route('/dashboard', methods=['GET', 'POST'])
@login_required
def dashboard():
    user_id = session.get('user_id')
    user = User.query.get(user_id)

    if not user:
        flash("User not found. Please log in again.", "danger")
        return redirect(url_for('login'))

    # --- ADMIN DASHBOARD ---
    if user.role == 'admin':
        # Get stats for admin dashboard
        total_users = User.query.count()
        total_landlords = User.query.filter_by(role='landlord').count()
        total_tenants = User.query.filter_by(role='tenant').count()
        total_properties = Property.query.count()
        
        # Get pending verification requests
        pending_verifications = User.query.filter_by(
            role='landlord', 
            is_approved_by_admin=False
        ).count()
        
        # Get pending support tickets
        pending_tickets = HelpSupport.query.filter_by(status='pending').count()
        
        # Get commission data
        paid_bills = Billing.query.filter_by(status='paid').all()
        total_commission = sum(bill.admin_commission or 0 for bill in paid_bills)
        
        # Calculate pending commission (unpaid bills)
        unpaid_bills = Billing.query.filter_by(status='unpaid').all()
        pending_commission = sum(bill.amount * 0.05 for bill in unpaid_bills)  # 5% commission
        
        # Recent activities
        recent_tickets = HelpSupport.query.order_by(HelpSupport.timestamp.desc()).limit(5).all()
        recent_users = User.query.order_by(User.created_at.desc()).limit(5).all()
        
        return render_template(
            'admin_dashboard.html',
            user=user,
            # Stats
            total_users=total_users,
            total_landlords=total_landlords,
            total_tenants=total_tenants,
            total_properties=total_properties,
            pending_verifications=pending_verifications,
            pending_tickets=pending_tickets,
            total_commission=total_commission,
            pending_commission=pending_commission,
            # Recent activities
            recent_tickets=recent_tickets,
            recent_users=recent_users
        )

    # --- LANDLORD DASHBOARD ---
    elif user.role == 'landlord':
        # Handle trend image upload for landlords
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

        # Load trend image
        chart_image = getattr(user, 'trend_image', None)

        # Get landlord's properties and data
        properties = Property.query.filter_by(landlord_id=user.id).all()
        property_ids = [p.id for p in properties]
        
        # Get pending bookings for landlord's properties
        pending_bookings = Booking.query.filter(
            Booking.property_id.in_(property_ids),
            Booking.status == 'pending'
        ).all()
        
        # Get bills for landlord's properties
        tenant_bills = []
        for prop in properties:
            tenant_bills.extend(getattr(prop, 'bills', []))

        # Fetch policies relevant to the user
        relevant_policies = Policy.query.filter(
            (Policy.applicable_role == user.role) | (Policy.applicable_role == 'all')
        ).all()

        return render_template(
            'dashboard.html',
            user=user,
            properties=properties,
            pending_bookings=pending_bookings,
            tenant_bills=tenant_bills,
            chart_image=chart_image,
            policies=relevant_policies
        )

    # --- TENANT DASHBOARD ---
    elif user.role == 'tenant':
        # Get tenant's bookings
        bookings = Booking.query.filter_by(tenant_id=user.id).all()
        pending_bookings = [b for b in bookings if b.status == 'pending']
        
        # Get tenant's bills
        tenant_bills = Billing.query.filter_by(tenant_id=user.id).all()
        
        # Get trend image from first approved booking's property owner
        chart_image = None
        approved_booking = Booking.query.filter_by(
            tenant_id=user.id, 
            status='approved'
        ).first()
        if approved_booking and approved_booking.property and approved_booking.property.owner:
            chart_image = getattr(approved_booking.property.owner, 'trend_image', None)

        # Fetch policies relevant to the user
        relevant_policies = Policy.query.filter(
            (Policy.applicable_role == user.role) | (Policy.applicable_role == 'all')
        ).all()

        return render_template(
            'dashboard.html',
            user=user,
            properties=bookings,  # For tenants, show their bookings as "properties"
            pending_bookings=pending_bookings,
            tenant_bills=tenant_bills,
            chart_image=chart_image,
            policies=relevant_policies
        )

    # --- FALLBACK: If user role is not recognized ---
    else:
        flash("Unknown user role. Please contact support.", "danger")
        return redirect(url_for('logout'))

@app.route('/billing')
@login_required
def billing():
    user = current_user
    current_year = date.today().year  # Add this for the template

    # Get bills depending on role
    if user.role == 'landlord':
        bills = Billing.query.join(Property).filter(Property.landlord_id == user.id).all()
    else:  # tenant
        bills = Billing.query.filter_by(tenant_id=user.id).all()

    # Apply penalties and discounts to the actual bill fields (not current_penalty/discount)
    for bill in bills:
        # Auto-apply penalties for overdue bills
        if bill.status.lower() == 'unpaid' and bill.due_date:
            if date.today() > bill.due_date:
                # Apply penalty directly to the bill
                bill.penalty = bill.amount * 0.1  # 10% penalty
                bill.status = 'overdue'  # Update status to overdue
            else:
                bill.penalty = 0  # Reset penalty if not overdue
        
        # Auto-apply discounts for early payments
        if bill.status.lower() == 'paid' and hasattr(bill, 'payment_date') and bill.due_date:
            if bill.payment_date <= bill.due_date:
                bill.discount = bill.amount * 0.05  # 5% discount
            else:
                bill.discount = 0  # No discount if paid late

    # Commit the changes to the database
    db.session.commit()

    return render_template('billing.html', bills=bills, user=user, current_year=current_year)

@app.route('/fix-database')
def fix_database():
    """Add the missing is_approved_by_admin column"""
    try:
        # Add the missing column
        db.engine.execute('ALTER TABLE user ADD COLUMN is_approved_by_admin BOOLEAN DEFAULT FALSE')
        
        # Set existing landlords as approved for testing
        landlords = User.query.filter_by(role='landlord').all()
        for landlord in landlords:
            landlord.is_approved_by_admin = True
            print(f"Approved landlord: {landlord.name}")
        
        # Set admin as approved
        admin = User.query.filter_by(role='admin').first()
        if admin:
            admin.is_approved_by_admin = True
        
        db.session.commit()
        return "✅ Database fixed! Added is_approved_by_admin column and approved existing users."
    except Exception as e:
        return f"Error: {str(e)}"




# ---------- View Properties Route ----------
@app.route('/properties')
@login_required
def viewproperties():
    user = User.query.get(session.get('user_id'))
    if not user:
        flash("User not found.", "danger")
        return redirect(url_for('login'))

    if user.role == 'landlord':
        properties = Property.query.filter_by(landlord_id=user.id).all()
    else:
        properties = Property.query.all()

    # Prepare property info for template
    property_data = []
    for prop in properties:
        # Get total slots
        total_slots = prop.slots if prop.slots is not None else 10
        
        # Count ONLY approved bookings to calculate available slots
        approved_bookings_count = sum(1 for booking in prop.bookings if booking.status == 'approved')
        
        # Calculate actual slots left
        slots_left = max(0, total_slots - approved_bookings_count)
        
        # Check if current user has booked this property
        user_has_booked = any(b.tenant_id == user.id for b in prop.bookings)
        
        property_data.append({
            'property': prop,
            'slots_left': slots_left,
            'total_slots': total_slots,
            'user_has_booked': user_has_booked
        })

    return render_template('viewproperties.html', properties=property_data, user=user)

@app.route('/logout')
@login_required
def logout():
    session.pop('user_id', None)
    session.pop('user_role', None)
    session.pop('user_name', None)
    flash("You have been logged out.", "info")
    return redirect(url_for('login'))

@app.route('/landlord/booked_properties')
@login_required
@verified_landlord_required
def booked_properties():
    user = User.query.get(session.get('user_id'))

    # Ensure the user is a landlord
    if not user or user.role != 'landlord':
        flash("Access denied. You must be a landlord to view this page.", "danger")
        return redirect(url_for('home'))

    # Fetch all properties of this landlord
    properties = Property.query.filter_by(landlord_id=user.id).all()

    booked_properties = []

    # Collect all bookings for each property
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
  








@app.route('/buy_property/<int:property_id>', methods=['POST'])
def buy_property(property_id):
    property = Property.query.get_or_404(property_id)
    # Handle the booking/payment logic here
    property.status = 'booked'  # Change status to booked
    db.session.commit()
    flash(f"Property {property.title} has been booked!", "success")
    return redirect(url_for('dashboard'))  # Redirect to the dashboard

    

@app.route('/my_bookings_tenant')
@login_required
def my_bookings_tenant_page():
    user = User.query.get(session.get('user_id'))

    if not user or user.role != 'tenant':
        flash("Access denied. You must be a tenant to view this page.", "danger")
        return redirect(url_for('dashboard'))

    # Fetch tenant's bookings
    bookings = Booking.query.filter_by(tenant_id=user.id).all()

    return render_template('tenants_booking.html', bookings=bookings, user=user)



@app.route('/add_property', methods=['GET', 'POST'])
@login_required
@verified_landlord_required
def add_property():
    user = User.query.get(session.get('user_id'))
    
    # DEBUG: Check user status
    print(f"=== DEBUG ADD PROPERTY ===")
    print(f"User: {user.name if user else 'None'}")
    print(f"User role: {user.role if user else 'None'}")
    print(f"User verified: {user.is_verified if user else 'None'}")
    print(f"User approved by admin: {getattr(user, 'is_approved_by_admin', 'NO ATTR')}")
    
    # Check if user is a landlord (temporarily skip verification for testing)
    if not user or user.role != 'landlord':
        flash("Only landlords can add properties.", "danger")
        return redirect(url_for('dashboard'))
    
    # TEMPORARY: Skip full verification for testing
    # if not user.is_verified_landlord():
    #     flash("Please verify your email and get admin approval first.", "danger")
    #     return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        print("=== FORM SUBMISSION DETECTED ===")
        print(f"Form data: {dict(request.form)}")
        
        try:
            # Get form data with proper validation
            title = request.form.get('title', '').strip()
            description = request.form.get('description', '').strip()
            price = request.form.get('price', '0')
            location = request.form.get('location', '').strip()
            gender_preference = request.form.get('gender_preference')
            property_type = request.form.get('property_type')
            bedrooms = request.form.get('bedrooms', '0')
            bathrooms = request.form.get('bathrooms', '0')
            slots = request.form.get('slots', '10')
            amenities = request.form.getlist('amenities')  # This returns a list

            # Debug form data
            print(f"Title: {title}")
            print(f"Description: {description[:50]}...")
            print(f"Price: {price}")
            print(f"Location: {location}")
            print(f"Gender Preference: {gender_preference}")
            print(f"Property Type: {property_type}")
            print(f"Bedrooms: {bedrooms}")
            print(f"Bathrooms: {bathrooms}")
            print(f"Slots: {slots}")
            print(f"Amenities: {amenities}")
            
            # Validate required fields
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

            # Convert numeric fields
            try:
                price = float(price)
                slots = int(slots)
                bedrooms = int(bedrooms) if bedrooms and bedrooms != '0' else None
                bathrooms = float(bathrooms) if bathrooms and bathrooms != '0' else None
            except ValueError as e:
                flash(f"Invalid number format: {str(e)}", "danger")
                return redirect(request.url)

            # Validate price and slots
            if price <= 0:
                flash("Price must be greater than 0.", "danger")
                return redirect(request.url)
                
            if slots <= 0:
                flash("Slots must be greater than 0.", "danger")
                return redirect(request.url)

            # Handle file uploads
            files = request.files.getlist('images')
            print(f"Number of images: {len(files)}")
            
            if len(files) > app.config['MAX_IMAGE_COUNT']:
                flash(f"Maximum {app.config['MAX_IMAGE_COUNT']} images allowed.", "danger")
                return redirect(request.url)

            main_image = None
            image_filenames = []
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

            # Process uploaded images
            for idx, file in enumerate(files):
                if file and file.filename != '':
                    print(f"Processing file {idx}: {file.filename}")
                    if not allowed_file(file):
                        flash(f"File not allowed or too large: {file.filename}. Please use PNG, JPG, or JPEG files under 5MB.", "danger")
                        continue

                    original_filename = secure_filename(file.filename)
                    unique_filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{original_filename}"
                    upload_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)

                    try:
                        file.save(upload_path)
                        image_filenames.append(unique_filename)
                        if idx == 0:  # First image is the main image
                            main_image = unique_filename
                        print(f"Saved image: {unique_filename}")
                    except Exception as e:
                        print(f"Error saving file {file.filename}: {e}")
                        flash(f"Error saving file {file.filename}", "danger")

            # Create and save the property
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
                amenities=','.join(amenities) if amenities else None  # Store amenities as comma-separated string
            )

            db.session.add(new_property)
            db.session.flush()  # Get the ID without committing
            
            print(f"New property created with ID: {new_property.id}")

            # Save additional images to PropertyImage table
            for fname in image_filenames:
                # Skip the main image since it's already saved in Property.image
                if fname != main_image:
                    prop_image = PropertyImage(property_id=new_property.id, filename=fname)
                    db.session.add(prop_image)
                    print(f"Added additional image: {fname}")

            # Commit everything
            db.session.commit()
            print("=== PROPERTY ADDED SUCCESSFULLY ===")

            flash("Property added successfully!", "success")
            return redirect(url_for('viewproperties'))
            
        except Exception as e:
            db.session.rollback()
            print(f"=== ERROR ADDING PROPERTY: {str(e)} ===")
            import traceback
            print(f"Full traceback: {traceback.format_exc()}")
            flash(f"Error adding property: {str(e)}", "danger")
            return redirect(request.url)

    return render_template('add_property.html', user=user)

@app.route('/fix-property-model')
def fix_property_model():
    """Add the missing amenities column to Property table"""
    try:
        # Check if column exists
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('property')]
        
        if 'amenities' not in columns:
            db.engine.execute('ALTER TABLE property ADD COLUMN amenities TEXT')
            return "✅ Added amenities column to Property table!"
        else:
            return "✅ Amenities column already exists!"
    except Exception as e:
        return f"Error: {str(e)}"
    

    
# Admin verification dashboard
@app.route('/admin/verify')
@login_required
def admin_verify():
    if current_user.role != 'admin':
        flash("Unauthorized access!", "danger")
        return redirect(url_for('dashboard'))

    # Landlords not yet approved by admin (check both fields)
    unverified_landlords = User.query.filter_by(role='landlord').filter(
        (User.is_approved_by_admin == False) | (User.is_verified == False)
    ).all()
    return render_template('admin_verify.html', unverified_users=unverified_landlords)
# Approve landlord
@app.route('/admin/verify/<int:user_id>', methods=['POST'])
@login_required
def verify_landlord(user_id):
    if current_user.role != 'admin':
        flash("Unauthorized access!", "danger")
        return redirect(url_for('dashboard'))

    user = User.query.get_or_404(user_id)
    user.is_approved_by_admin = True  # This is the key line!
    user.is_verified = True  # Also verify their email
    db.session.commit()
    flash(f"Landlord {user.name} has been approved by admin!", "success")
    return redirect(url_for('admin_verify'))

# Reject landlord
@app.route('/admin/reject/<int:user_id>', methods=['POST'])
@login_required
def reject_landlord(user_id):
    if current_user.role != 'admin':
        flash("Unauthorized access!", "danger")
        return redirect(url_for('dashboard'))

    user = User.query.get_or_404(user_id)
    user.is_approved_by_admin = False  # Explicitly reject
    db.session.commit()
    flash(f"Landlord {user.name} has been rejected by admin.", "warning")
    return redirect(url_for('admin_verify'))

@app.route('/add-admin-approval-column')
def add_admin_approval_column():
    """Add the missing is_approved_by_admin column to database"""
    try:
        db.engine.execute('ALTER TABLE user ADD COLUMN is_approved_by_admin BOOLEAN DEFAULT FALSE')
        
        # Set existing landlords as approved for testing
        landlords = User.query.filter_by(role='landlord').all()
        for landlord in landlords:
            landlord.is_approved_by_admin = True
        db.session.commit()
        
        return "✅ Added is_approved_by_admin column and approved existing landlords!"
    except Exception as e:
        return f"Column might already exist: {str(e)}"

    
@app.route('/book_property/<int:property_id>', methods=['POST'])
@login_required
def book_property(property_id):
    property = Property.query.get_or_404(property_id)
    
    # DEBUG: Print all form data
    print("=== DEBUG FORM DATA ===")
    print(f"Form data: {dict(request.form)}")
    
    start_date = request.form.get('start_date')
    end_date = request.form.get('end_date')
    
    print(f"Start date from form: {start_date}")
    print(f"End date from form: {end_date}")
    
    if not start_date or not end_date:
        flash("Please provide both start and end dates.", "danger")
        return redirect(url_for('property_detail', property_id=property.id))
    
    # Convert dates
    try:
        start_date_obj = datetime.strptime(start_date, "%Y-%m-%d").date()
        end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").date()
        
        print(f"Parsed start date: {start_date_obj}")
        print(f"Parsed end date: {end_date_obj}")
        
        if end_date_obj <= start_date_obj:
            flash("End date must be after start date.", "danger")
            return redirect(url_for('property_detail', property_id=property.id))
            
    except ValueError as e:
        print(f"Date parsing error: {e}")
        flash("Invalid date format. Please use YYYY-MM-DD.", "danger")
        return redirect(url_for('property_detail', property_id=property.id))
    
    # Check available slots
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
    
    # SIMPLE CALCULATION (same as frontend)
    total_days = (end_date_obj - start_date_obj).days
    monthly_rate = property.price
    daily_rate = monthly_rate / 30
    
    total_bill = total_days * daily_rate
    
    print(f"=== BACKEND CALCULATION ===")
    print(f"Total days: {total_days}")
    print(f"Monthly rate: {monthly_rate}")
    print(f"Daily rate: {daily_rate:.2f}")
    print(f"Total bill: {total_bill:.2f}")
    
    # Create booking and billing
    booking = Booking(
        property_id=property.id,
        tenant_id=current_user.id,
        start_date=start_date_obj,
        end_date=end_date_obj,
        status='pending',
        total_bill=total_bill
    )
    db.session.add(booking)
    
    billing = Billing(
        tenant_id=current_user.id,
        property_id=property.id,
        amount=total_bill,
        status='unpaid',
        due_date=end_date_obj
    )
    db.session.add(billing)
    db.session.commit()
    
    flash(
        f"Booking requested! {total_days} days × ₱{daily_rate:.2f}/day = ₱{total_bill:,.2f}. Waiting for approval.", 
        "success"
    )
    
    return redirect(url_for('property_detail', property_id=property.id))


@app.route('/add-amenities-column')
def add_amenities_column():
    """Add the missing amenities column to property table"""
    try:
        # Add the amenities column
        db.engine.execute('ALTER TABLE property ADD COLUMN amenities TEXT')
        
        # Verify it was added
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('property')]
        
        if 'amenities' in columns:
            return "✅ Successfully added 'amenities' column to property table!"
        else:
            return "❌ Failed to add amenities column"
    except Exception as e:
        return f"Error: {str(e)}"
    

@app.route('/check-property-schema')
def check_property_schema():
    """Check current property table columns"""
    from sqlalchemy import inspect
    inspector = inspect(db.engine)
    columns = inspector.get_columns('property')
    
    result = "<h2>Property Table Columns:</h2><ul>"
    for col in columns:
        result += f"<li>{col['name']} ({col['type']})</li>"
    result += "</ul>"
    
    return result


@app.route('/reset-db-fix-amenities')
def reset_db_fix_amenities():
    """Completely reset database with correct schema"""
    try:
        print("=== STARTING DATABASE RESET ===")
        
        # Drop all tables
        db.drop_all()
        print("✅ Dropped all tables")
        
        # Create all tables with updated schema
        db.create_all()
        print("✅ Created all tables with updated schema")
        
        # Recreate admin user
        from werkzeug.security import generate_password_hash
        admin = User(
            name="Admin",
            email="admin@example.com",
            password_hash=generate_password_hash("admin123", method="pbkdf2:sha256"),
            role="admin",
            is_verified=True,
            is_approved_by_admin=True,
            gender="Prefer not to say",
            birthdate=date(1990, 1, 1)
        )
        db.session.add(admin)
        db.session.commit()
        print("✅ Created admin user")
        
        # Verify the amenities column exists
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('property')]
        
        print(f"Property table columns: {columns}")
        
        if 'amenities' in columns:
            return """
            <h2>✅ Database Successfully Reset!</h2>
            <p>Amenities column now exists in property table.</p>
            <p><a href="/add_property">Try adding a property now</a></p>
            <p><strong>Property table columns:</strong> {}</p>
            """.format(', '.join(columns))
        else:
            return "❌ Amenities column still missing after reset"
            
    except Exception as e:
        import traceback
        return f"""
        <h2>❌ Error during reset</h2>
        <p><strong>Error:</strong> {str(e)}</p>
        <pre>{traceback.format_exc()}</pre>
        """

@app.route('/fix-all-issues')
def fix_all_issues():
    """Fix all database issues manually"""
    try:
        # Check and add amenities column if missing
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        
        # Fix property table
        property_columns = [col['name'] for col in inspector.get_columns('property')]
        if 'amenities' not in property_columns:
            db.engine.execute('ALTER TABLE property ADD COLUMN amenities TEXT')
            print("✅ Added amenities column to property")
        
        # Fix any other missing columns you might have
        # Add more fixes here as needed...
        
        db.session.commit()
        return "✅ All database issues fixed!"
        
    except Exception as e:
        return f"Error: {str(e)}"

# --- Scheduler Setup ---
scheduler = BackgroundScheduler()

# Run penalty checker daily
scheduler.add_job(apply_penalties, 'interval', days=1)

# Run discount checker daily
scheduler.add_job(apply_discounts, 'interval', days=1)

# Run SMS reminders monthly
scheduler.add_job(send_monthly_sms, 'interval', days=30)

scheduler.start()






# ----------------- Create DB -----------------
# Run this command once to create the necessary database tables
with app.app_context():
    db.create_all()

# ----------------- Run App -----------------
if __name__ == "__main__":
    app.run(debug=True)
