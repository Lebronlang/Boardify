from flask_sqlalchemy import SQLAlchemy
from datetime import date, datetime, timedelta
from flask_login import UserMixin
import secrets
import string

db = SQLAlchemy()

def generate_booking_reference():
    """Generate a unique 8-character booking reference"""
    characters = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(characters) for _ in range(8))

class User(db.Model, UserMixin):
    __tablename__ = 'user'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(50), nullable=False, default='user')
    
    # Email verification fields
    is_verified = db.Column(db.Boolean, default=False)
    verification_token = db.Column(db.String(100), nullable=True)
    
    # Admin approval for landlords
    is_approved_by_admin = db.Column(db.Boolean, default=False)
    
    # Personal information
    gender = db.Column(db.String(20), nullable=True)
    birthdate = db.Column(db.Date, nullable=True)
    
    # Optional images
    profile_pic = db.Column(db.String(150), default='default.jpg')
    trend_image = db.Column(db.String(150), nullable=True)
    license_image = db.Column(db.String(150), nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    properties = db.relationship('Property', back_populates='owner', lazy='dynamic')
    bills = db.relationship('Billing', back_populates='tenant', lazy='dynamic')
    bookings = db.relationship('Booking', back_populates='tenant', lazy='dynamic')
    
    sent_messages = db.relationship('Message', foreign_keys='Message.sender_id',
                                    back_populates='sender', lazy='dynamic')
    received_messages = db.relationship('Message', foreign_keys='Message.receiver_id',
                                        back_populates='receiver', lazy='dynamic')

    def get_id(self):
        return str(self.id)
    
    def is_admin(self):
        return self.role == 'admin'
    
    def is_landlord(self):
        return self.role == 'landlord'
    
    def is_tenant(self):
        return self.role == 'tenant'
    
    def is_verified_landlord(self):
        return self.role == 'landlord' and self.is_verified and self.is_approved_by_admin
    
    def get_age(self):
        if not self.birthdate:
            return None
        today = date.today()
        return today.year - self.birthdate.year - ((today.month, today.day) < (self.birthdate.month, self.birthdate.day))
    
    def get_gender_display(self):
        gender_map = {
            'male': 'Male',
            'female': 'Female', 
            'other': 'Other',
            'prefer_not_to_say': 'Prefer not to say'
        }
        return gender_map.get(self.gender, 'Not specified')
    
    def get_birthdate_display(self):
        if not self.birthdate:
            return 'Not specified'
        return self.birthdate.strftime('%B %d, %Y')

class Property(db.Model):
    __tablename__ = 'property'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    price = db.Column(db.Float, nullable=False)
    location = db.Column(db.String(150), nullable=True)
    gender_preference = db.Column(db.String(50), nullable=True)
    property_type = db.Column(db.String(50), nullable=True)
    bedrooms = db.Column(db.Integer, nullable=True)
    bathrooms = db.Column(db.Integer, nullable=True)
    image = db.Column(db.String(200), nullable=True)
    status = db.Column(db.String(50), default='available')
    landlord_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    slots = db.Column(db.Integer, default=10)
    amenities = db.Column(db.Text, nullable=True)

    # Relationships - KEEP ORIGINAL NAMES
    owner = db.relationship('User', back_populates='properties')
    bills = db.relationship('Billing', back_populates='property', lazy=True)
    bookings = db.relationship('Booking', back_populates='property', lazy=True)
    images = db.relationship('PropertyImage', back_populates='property', lazy=True, cascade='all, delete-orphan')
    reviews = db.relationship('Review', back_populates='property', lazy=True)

    @property
    def daily_rate(self):
        return self.price / 30

    def __repr__(self):
        return f'<Property {self.title} | Status: {self.status}>'

class Review(db.Model):
    __tablename__ = 'review'
    
    id = db.Column(db.Integer, primary_key=True)
    property_id = db.Column(db.Integer, db.ForeignKey('property.id'), nullable=False)
    tenant_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    rating = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships - USE UNIQUE BACKREF FOR USER
    property = db.relationship('Property', back_populates='reviews')
    tenant = db.relationship('User', backref=db.backref('user_reviews', lazy=True))
    
    def __repr__(self):
        return f'<Review {self.id} - Property {self.property_id} - Rating {self.rating}>'

class Billing(db.Model):
    __tablename__ = 'billing'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    property_id = db.Column(db.Integer, db.ForeignKey('property.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='unpaid')
    payment_method = db.Column(db.String(50), nullable=True)
    months = db.Column(db.Integer, default=1)
    due_date = db.Column(db.Date, nullable=True)
    penalty = db.Column(db.Float, default=0.0)
    discount = db.Column(db.Float, default=0.0)
    sms_sent = db.Column(db.Boolean, default=False)
    admin_commission = db.Column(db.Float, default=0)
    booking_reference = db.Column(db.String(20), nullable=True)

    # Relationships
    tenant = db.relationship('User', back_populates='bills')
    property = db.relationship('Property', back_populates='bills')

    def update_penalty_discount(self):
        if not self.due_date:
            return

        today = date.today()
        self.penalty = max(0, (today - self.due_date).days * 20) if today > self.due_date else 0
        self.discount = self.amount * 0.05 if today < self.due_date - timedelta(days=7) else 0

        if today > self.due_date and self.status == 'unpaid':
            self.status = 'overdue'

class PropertyImage(db.Model):
    __tablename__ = 'property_images'

    id = db.Column(db.Integer, primary_key=True)
    property_id = db.Column(db.Integer, db.ForeignKey('property.id'), nullable=False)
    filename = db.Column(db.String(200), nullable=False)

    # Relationship
    property = db.relationship('Property', back_populates='images')

    def __repr__(self):
        return f"<PropertyImage {self.filename} for Property {self.property_id}>"

class Booking(db.Model):
    __tablename__ = 'booking'

    id = db.Column(db.Integer, primary_key=True)
    reference_number = db.Column(db.String(20), unique=True, default=generate_booking_reference)
    tenant_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    property_id = db.Column(db.Integer, db.ForeignKey('property.id'), nullable=False)
    start_date = db.Column(db.Date, nullable=False, default=date.today)
    end_date = db.Column(db.Date, nullable=True)
    total_bill = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    tenant = db.relationship('User', back_populates='bookings')
    property = db.relationship('Property', back_populates='bookings')

    def __repr__(self):
        return f'<Booking {self.reference_number} - {self.property.title if self.property else "Unknown"} - {self.status}>'

class Message(db.Model):
    __tablename__ = 'messages'

    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    sender = db.relationship('User', foreign_keys=[sender_id], back_populates='sent_messages')
    receiver = db.relationship('User', foreign_keys=[receiver_id], back_populates='received_messages')

class Policy(db.Model):
    __tablename__ = 'policy'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    content = db.Column(db.Text, nullable=False)
    applicable_role = db.Column(db.String(50), nullable=False)

    def __repr__(self):
        return f"<Policy {self.title} | Role: {self.applicable_role}>"

class HelpSupport(db.Model):
    __tablename__ = 'help_support'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    subject = db.Column(db.String(255), nullable=False)
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default='pending')
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('help_support_tickets', lazy=True))

    def __repr__(self):
        return f"<HelpSupport(id={self.id}, subject='{self.subject}', user_id={self.user_id}, status='{self.status}')>"