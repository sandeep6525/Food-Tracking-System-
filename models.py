from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), default='user')
    created_at = Column(DateTime, default=datetime.utcnow)

class Customer(Base):
    __tablename__ = 'customers'
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    contact = Column(String(255))
    address = Column(Text)
    notes = Column(Text)
    shipments = relationship('Shipment', back_populates='customer')

class Shipment(Base):
    __tablename__ = 'shipments'
    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)

    # Replaces grade with specific tomato type
    tomato_type = Column(String(50))

    quantity_kg = Column(Float, default=0)

    origin_name = Column(String(255), nullable=False)
    origin_lat = Column(Float, nullable=False)
    origin_lng = Column(Float, nullable=False)
    dest_name = Column(String(255), nullable=False)
    dest_lat = Column(Float, nullable=False)
    dest_lng = Column(Float, nullable=False)

    distance_km = Column(Float)
    drive_time_hours = Column(Float)
    eta_days = Column(Float)

    planned_start = Column(DateTime)
    planned_arrival = Column(DateTime)

    avg_temp_c = Column(Float)
    rain_risk = Column(String(20))  # low/medium/high
    road_type = Column(String(50))  # highway/mixed/poor

    condition_departure = Column(String(100))
    condition_arrival = Column(String(100))

    status = Column(String(50), default='planned')
    actual_start = Column(DateTime)
    delivered_at = Column(DateTime)

    customer_id = Column(Integer, ForeignKey('customers.id'))
    customer = relationship('Customer', back_populates='shipments')

    created_by = Column(Integer, ForeignKey('users.id'))
    created_at = Column(DateTime, default=datetime.utcnow)

class Timeline(Base):
    __tablename__ = 'timeline'
    id = Column(Integer, primary_key=True)
    shipment_id = Column(Integer, ForeignKey('shipments.id'), nullable=False)
    ts = Column(DateTime, default=datetime.utcnow)
    note = Column(Text)

class TomatoType(Base):
    __tablename__ = 'tomato_types'
    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, nullable=False)
    best_temp_min = Column(Float)
    best_temp_max = Column(Float)
    max_travel_days = Column(Integer)
    notes = Column(Text)
