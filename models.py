from flask_sqlalchemy import SQLAlchemy
from datetime import date, datetime, timedelta
from flask_login import UserMixin
import secrets
import string


db = SQLAlchemy()

def generate_booking_reference():
    """Generate a unique 8-character booking reference number"""
    characters = string.ascii_uppercase + string.digits
    reference = ''.join(secrets.choice(characters) for _ in range(8))
    
    # Ensure uniqueness by checking database
    while Booking.query.filter_by(reference_number=reference).first():
        reference = ''.join(secrets.choice(characters) for _ in range(8))
    
    return reference

class User(db.Model, UserMixin):
    """User model for tenants, landlords, and admins"""
    __tablename__ = 'user'
    
    # Primary key
    id = db.Column(db.Integer, primary_key=True)
    
    # Basic information
    name = db.Column(db.String(150), nullable=False, index=True)
    email = db.Column(db.String(150), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(50), nullable=False, default='tenant', index=True)
    
    # Email verification fields
    is_verified = db.Column(db.Boolean, default=False, nullable=False, index=True)
    verification_token = db.Column(db.String(200), nullable=True)  # Increased size for tokens
    verification_sent_at = db.Column(db.DateTime, nullable=True)  # NEW: Track when verification was sent
    
    # Admin approval for landlords
    is_approved_by_admin = db.Column(db.Boolean, default=False, nullable=False, index=True)
    approved_at = db.Column(db.DateTime, nullable=True)  # NEW: Track when approved
    
    # Personal information
    gender = db.Column(db.String(20), nullable=True)
    birthdate = db.Column(db.Date, nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    bio = db.Column(db.Text, nullable=True)
    
    # Images
    profile_pic = db.Column(db.String(200), default='default.jpg')
    trend_image = db.Column(db.String(200), nullable=True)
    license_image = db.Column(db.String(200), nullable=True)
    
    # Account status
    is_active = db.Column(db.Boolean, default=True, nullable=False)  # NEW: For soft deletes
    last_login = db.Column(db.DateTime, nullable=True)  # NEW: Track last login
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    properties = db.relationship('Property', back_populates='owner', lazy='dynamic', cascade='all, delete-orphan')
    bills = db.relationship('Billing', back_populates='tenant', lazy='dynamic', foreign_keys='Billing.tenant_id')
    bookings = db.relationship('Booking', back_populates='tenant', lazy='dynamic', cascade='all, delete-orphan')
    
    sent_messages = db.relationship('Message', foreign_keys='Message.sender_id',
                                    back_populates='sender', lazy='dynamic', cascade='all, delete-orphan')
    received_messages = db.relationship('Message', foreign_keys='Message.receiver_id',
                                        back_populates='receiver', lazy='dynamic', cascade='all, delete-orphan')
    
    help_tickets = db.relationship('HelpSupport', back_populates='user', lazy='dynamic', cascade='all, delete-orphan')
    reviews = db.relationship('Review', back_populates='tenant', lazy='dynamic', cascade='all, delete-orphan')

    def get_id(self):
        """Required by Flask-Login"""
        return str(self.id)
    
    def is_admin(self):
        """Check if user is admin"""
        return self.role == 'admin'
    
    def is_landlord(self):
        """Check if user is landlord"""
        return self.role == 'landlord'
    
    def is_tenant(self):
        """Check if user is tenant"""
        return self.role == 'tenant'
    
    def is_verified_landlord(self):
        """Check if landlord is fully verified"""
        return self.role == 'landlord' and self.is_verified and self.is_approved_by_admin
    
    def get_age(self):
        """Calculate user's age from birthdate"""
        if not self.birthdate:
            return None
        today = date.today()
        return today.year - self.birthdate.year - ((today.month, today.day) < (self.birthdate.month, self.birthdate.day))
    
    def get_gender_display(self):
        """Get formatted gender display"""
        gender_map = {
            'male': 'Male',
            'female': 'Female', 
            'other': 'Other',
            'prefer_not_to_say': 'Prefer not to say'
        }
        return gender_map.get(self.gender, 'Not specified')
    
    def get_birthdate_display(self):
        """Get formatted birthdate display"""
        if not self.birthdate:
            return 'Not specified'
        return self.birthdate.strftime('%B %d, %Y')
    
    def update_last_login(self):
        """Update last login timestamp"""
        self.last_login = datetime.utcnow()
        db.session.commit()
    
    def can_resend_verification(self):
        """Check if user can resend verification email (1 hour cooldown)"""
        if not self.verification_sent_at:
            return True
        time_since_last = datetime.utcnow() - self.verification_sent_at
        return time_since_last.total_seconds() > 3600  # 1 hour cooldown
    
    def __repr__(self):
        return f'<User {self.id}: {self.name} ({self.role})>'

class Property(db.Model):
    """Property model for rental listings"""
    __tablename__ = 'property'
    
    # Primary key
    id = db.Column(db.Integer, primary_key=True)
    
    # Basic information
    title = db.Column(db.String(200), nullable=False, index=True)
    description = db.Column(db.Text, nullable=False)
    price = db.Column(db.Float, nullable=False, index=True)
    location = db.Column(db.String(200), nullable=True, index=True)
    
    # Property details
    gender_preference = db.Column(db.String(50), nullable=True)
    property_type = db.Column(db.String(50), nullable=True, index=True)
    bedrooms = db.Column(db.Integer, nullable=True)
    bathrooms = db.Column(db.Float, nullable=True)
    slots = db.Column(db.Integer, default=10, nullable=False)
    amenities = db.Column(db.Text, nullable=True)
    
    # Media
    image = db.Column(db.String(200), nullable=True)
    
    # Status and ownership
    status = db.Column(db.String(50), default='available', nullable=False, index=True)
    landlord_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    
    # NEW: View tracking
    view_count = db.Column(db.Integer, default=0, nullable=False)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    owner = db.relationship('User', back_populates='properties')
    bills = db.relationship('Billing', back_populates='property_obj', lazy='dynamic', cascade='all, delete-orphan')
    bookings = db.relationship('Booking', back_populates='property_obj', lazy='dynamic', cascade='all, delete-orphan')
    images = db.relationship('PropertyImage', back_populates='property_obj', lazy='dynamic', cascade='all, delete-orphan')
    reviews = db.relationship('Review', back_populates='property_obj', lazy='dynamic', cascade='all, delete-orphan')

    @property
    def daily_rate(self):
        """Calculate daily rate from monthly price"""
        return round(self.price / 30, 2)
    
    @property
    def available_slots(self):
        """Calculate available slots based on approved bookings"""
        approved_bookings = sum(1 for booking in self.bookings if booking.status == 'approved')
        return max(0, self.slots - approved_bookings)
    
    @property
    def is_available(self):
        """Check if property has available slots"""
        return self.available_slots > 0 and self.status == 'available'
    
    @property
    def average_rating(self):
        """Calculate average rating from reviews"""
        reviews_list = list(self.reviews)
        if not reviews_list:
            return 0
        return round(sum(r.rating for r in reviews_list) / len(reviews_list), 1)
    
    @property
    def review_count(self):
        """Get total number of reviews"""
        return self.reviews.count()
    
    @property
    def occupancy_rate(self):
        """Calculate occupancy rate percentage"""
        if self.slots == 0:
            return 0
        approved_bookings = sum(1 for booking in self.bookings if booking.status == 'approved')
        return round((approved_bookings / self.slots) * 100, 1)
    
    def get_amenities_list(self):
        """Get amenities as a list"""
        if not self.amenities:
            return []
        return [a.strip() for a in self.amenities.split(',') if a.strip()]
    
    def increment_view_count(self):
        """Increment property view count"""
        self.view_count += 1
        db.session.commit()

    def __repr__(self):
        return f'<Property {self.id}: {self.title} | Status: {self.status}>'

class PropertyImage(db.Model):
    """Property image model for multiple images per property"""
    __tablename__ = 'property_images'

    # Primary key
    id = db.Column(db.Integer, primary_key=True)
    
    # Foreign keys
    property_id = db.Column(db.Integer, db.ForeignKey('property.id', ondelete='CASCADE'), nullable=False, index=True)
    
    # Image data
    filename = db.Column(db.String(200), nullable=False)
    is_primary = db.Column(db.Boolean, default=False, nullable=False)  # NEW: Mark primary image
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Relationship (renamed to avoid conflict)
    property_obj = db.relationship('Property', back_populates='images')

    def __repr__(self):
        return f"<PropertyImage {self.id}: {self.filename} for Property {self.property_id}>"

class Booking(db.Model):
    """Booking model for property reservations"""
    __tablename__ = 'booking'

    # Primary key
    id = db.Column(db.Integer, primary_key=True)
    
    # Unique reference number
    reference_number = db.Column(db.String(20), unique=True, nullable=False, default=generate_booking_reference, index=True)
    
    # Foreign keys
    tenant_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    property_id = db.Column(db.Integer, db.ForeignKey('property.id', ondelete='CASCADE'), nullable=False, index=True)
    
    # Booking details
    start_date = db.Column(db.Date, nullable=False, default=date.today, index=True)
    end_date = db.Column(db.Date, nullable=False, index=True)
    total_bill = db.Column(db.Float, default=0.0, nullable=False)
    status = db.Column(db.String(20), default='pending', nullable=False, index=True)
    
    # NEW: Status tracking
    approved_at = db.Column(db.DateTime, nullable=True)
    rejected_at = db.Column(db.DateTime, nullable=True)
    rejection_reason = db.Column(db.Text, nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships (renamed to avoid conflict with @property decorator)
    tenant = db.relationship('User', back_populates='bookings')
    property_obj = db.relationship('Property', back_populates='bookings')

    @property
    def duration_days(self):
        """Calculate booking duration in days"""
        if not self.end_date or not self.start_date:
            return 0
        return (self.end_date - self.start_date).days
    
    @property
    def is_active(self):
        """Check if booking is currently active"""
        if self.status != 'approved':
            return False
        today = date.today()
        return self.start_date <= today <= self.end_date
    
    @property
    def is_upcoming(self):
        """Check if booking is upcoming"""
        return self.status == 'approved' and self.start_date > date.today()
    
    @property
    def is_past(self):
        """Check if booking is in the past"""
        return self.end_date and self.end_date < date.today()
    
    @property
    def status_badge_color(self):
        """Get Bootstrap color class for status badge"""
        status_colors = {
            'pending': 'warning',
            'approved': 'success',
            'rejected': 'danger',
            'cancelled': 'secondary',
            'completed': 'info'
        }
        return status_colors.get(self.status, 'secondary')
    
    # Add a property method to access the property object (for backward compatibility)
    @property
    def property(self):
        """Access property object - for backward compatibility"""
        return self.property_obj
    
    def approve(self):
        """Approve the booking"""
        self.status = 'approved'
        self.approved_at = datetime.utcnow()
        db.session.commit()
    
    def reject(self, reason=None):
        """Reject the booking"""
        self.status = 'rejected'
        self.rejected_at = datetime.utcnow()
        self.rejection_reason = reason
        db.session.commit()

    def __repr__(self):
        return f'<Booking {self.reference_number}: Property {self.property_id} - {self.status}>'

class Billing(db.Model):
    """Billing model for payment tracking"""
    __tablename__ = 'billing'

    # Primary key
    id = db.Column(db.Integer, primary_key=True)
    
    # Foreign keys
    tenant_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    property_id = db.Column(db.Integer, db.ForeignKey('property.id', ondelete='CASCADE'), nullable=False, index=True)
    
    # Billing details
    amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='unpaid', nullable=False, index=True)
    payment_method = db.Column(db.String(50), nullable=True)
    months = db.Column(db.Integer, default=1, nullable=False)
    
    # Dates
    due_date = db.Column(db.Date, nullable=True, index=True)
    payment_date = db.Column(db.Date, nullable=True)
    
    # Financial adjustments
    penalty = db.Column(db.Float, default=0.0, nullable=False)
    discount = db.Column(db.Float, default=0.0, nullable=False)
    admin_commission = db.Column(db.Float, default=0.0, nullable=False)
    
    # Communication
    sms_sent = db.Column(db.Boolean, default=False, nullable=False)
    reminder_sent = db.Column(db.Boolean, default=False, nullable=False)  # NEW: Track reminders
    
    # Reference to booking
    booking_reference = db.Column(db.String(20), nullable=True, index=True)
    
    # NEW: Transaction details
    transaction_id = db.Column(db.String(100), nullable=True, unique=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships (renamed to avoid conflict)
    tenant = db.relationship('User', back_populates='bills', foreign_keys=[tenant_id])
    property_obj = db.relationship('Property', back_populates='bills')

    @property
    def total_amount(self):
        """Calculate total amount including penalties and discounts"""
        base_amount = self.amount * self.months
        return base_amount + self.penalty - self.discount
    
    @property
    def is_overdue(self):
        """Check if bill is overdue"""
        if self.status == 'paid':
            return False
        if not self.due_date:
            return False
        return date.today() > self.due_date
    
    @property
    def days_overdue(self):
        """Calculate days overdue"""
        if not self.is_overdue:
            return 0
        return (date.today() - self.due_date).days
    
    @property
    def days_until_due(self):
        """Calculate days until due date"""
        if not self.due_date or self.status == 'paid':
            return 0
        days = (self.due_date - date.today()).days
        return max(0, days)
    
    # Add a property method to access the property object (for backward compatibility)
    @property
    def property(self):
        """Access property object - for backward compatibility"""
        return self.property_obj

    def update_penalty_discount(self):
        """Update penalty and discount based on payment status and dates"""
        if not self.due_date:
            return

        today = date.today()
        
        # Calculate penalty for overdue bills
        if self.status == 'unpaid' and today > self.due_date:
            days_late = (today - self.due_date).days
            self.penalty = days_late * 20  # ₱20 per day late
            self.status = 'overdue'
        else:
            self.penalty = 0
        
        # Calculate discount for early payment
        if self.status == 'paid' and self.payment_date and self.payment_date <= self.due_date:
            self.discount = self.amount * 0.05  # 5% discount
        else:
            self.discount = 0
    
    def mark_as_paid(self, payment_method, transaction_id=None):
        """Mark bill as paid"""
        self.status = 'paid'
        self.payment_date = date.today()
        self.payment_method = payment_method
        self.transaction_id = transaction_id
        self.update_penalty_discount()
        # Calculate admin commission (5%)
        self.admin_commission = self.total_amount * 0.05
        db.session.commit()
    
    def __repr__(self):
        return f'<Billing {self.id}: Tenant {self.tenant_id} - Property {self.property_id} - {self.status}>'

class Review(db.Model):
    """Review model for property ratings and feedback"""
    __tablename__ = 'review'
    
    # Primary key
    id = db.Column(db.Integer, primary_key=True)
    
    # Foreign keys
    property_id = db.Column(db.Integer, db.ForeignKey('property.id', ondelete='CASCADE'), nullable=False, index=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    
    # Review details
    rating = db.Column(db.Integer, nullable=False, index=True)
    comment = db.Column(db.Text, nullable=True)
    
    # NEW: Helpful tracking
    helpful_count = db.Column(db.Integer, default=0, nullable=False)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships (renamed to avoid conflict)
    property_obj = db.relationship('Property', back_populates='reviews')
    tenant = db.relationship('User', back_populates='reviews')
    
    # Add constraint to ensure rating is between 1 and 5
    __table_args__ = (
        db.CheckConstraint('rating >= 1 AND rating <= 5', name='check_rating_range'),
        db.UniqueConstraint('property_id', 'tenant_id', name='unique_property_tenant_review'),  # One review per tenant per property
    )
    
    @property
    def is_recent(self):
        """Check if review was created in the last 30 days"""
        return (datetime.utcnow() - self.created_at).days <= 30
    
    @property
    def rating_stars(self):
        """Get visual star representation"""
        return '⭐' * self.rating + '☆' * (5 - self.rating)
    
    # Add a property method to access the property object (for backward compatibility)
    @property
    def property(self):
        """Access property object - for backward compatibility"""
        return self.property_obj
    
    def __repr__(self):
        return f'<Review {self.id}: Property {self.property_id} - Rating {self.rating}/5>'

class Message(db.Model):
    """Message model for user-to-user communication"""
    __tablename__ = 'messages'

    # Primary key
    id = db.Column(db.Integer, primary_key=True)
    
    # Foreign keys
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    
    # Message content
    content = db.Column(db.Text, nullable=False)
    
    # Status
    is_read = db.Column(db.Boolean, default=False, nullable=False, index=True)
    read_at = db.Column(db.DateTime, nullable=True)  # NEW: Track when message was read
    
    # Timestamp
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Relationships
    sender = db.relationship('User', foreign_keys=[sender_id], back_populates='sent_messages')
    receiver = db.relationship('User', foreign_keys=[receiver_id], back_populates='received_messages')
    
    @property
    def is_recent(self):
        """Check if message was sent in the last hour"""
        return (datetime.utcnow() - self.timestamp).total_seconds() < 3600
    
    def mark_as_read(self):
        """Mark message as read"""
        if not self.is_read:
            self.is_read = True
            self.read_at = datetime.utcnow()
            db.session.commit()
    
    def __repr__(self):
        return f'<Message {self.id}: From {self.sender_id} to {self.receiver_id}>'

class Policy(db.Model):
    """Policy model for terms and conditions"""
    __tablename__ = 'policy'
    
    # Primary key
    id = db.Column(db.Integer, primary_key=True)
    
    # Policy details
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    applicable_role = db.Column(db.String(50), nullable=False, index=True)
    
    # Status
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    
    # NEW: Version tracking
    version = db.Column(db.String(20), default='1.0', nullable=False)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<Policy {self.id}: {self.title} | Role: {self.applicable_role}>"

class HelpSupport(db.Model):
    """Help and support ticket model"""
    __tablename__ = 'help_support'

    # Primary key
    id = db.Column(db.Integer, primary_key=True)
    
    # Foreign key - ONLY ONE foreign key for the main relationship
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    
    # Ticket details
    subject = db.Column(db.String(255), nullable=False)
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default='pending', nullable=False, index=True)
    priority = db.Column(db.String(20), default='normal', nullable=False)
    
    # Admin response - REMOVED the conflicting admin_id
    admin_response = db.Column(db.Text, nullable=True)
    resolved_at = db.Column(db.DateTime, nullable=True)
    
    # Timestamps
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationship - ONLY ONE relationship to User
    user = db.relationship('User', back_populates='help_tickets', foreign_keys=[user_id])
    
    @property
    def is_resolved(self):
        """Check if ticket is resolved"""
        return self.status == 'resolved'
    
    @property
    def is_pending(self):
        """Check if ticket is pending"""
        return self.status == 'pending'
    
    @property
    def resolution_time(self):
        """Calculate time to resolve ticket"""
        if not self.resolved_at:
            return None
        return (self.resolved_at - self.timestamp).total_seconds() / 3600  # Hours
    
    @property
    def age_hours(self):
        """Get ticket age in hours"""
        return (datetime.utcnow() - self.timestamp).total_seconds() / 3600

    def __repr__(self):
        return f"<HelpSupport {self.id}: {self.subject} - {self.status}>"