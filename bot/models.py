from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    username = Column(String(100), nullable=False)
    traffic_used = Column(Integer, default=0)
    trial_used = Column(Boolean, default=False)  # Добавлено поле trial_used
    terms_accepted = Column(Boolean, default=False)  # Добавлено поле для принятия условий
    subscription_expiry = Column(DateTime)  # Добавлено поле для срока подписки
    created_at = Column(DateTime, default=datetime.utcnow)  # Добавлено поле для даты создания
    is_active = Column(Boolean, default=True)  # Добавлено поле для активности

    def __repr__(self):
        return f"<User(id={self.id}, username={self.username}, traffic_used={self.traffic_used})>"
