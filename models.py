# models.py
from sqlalchemy import Column, Integer, String
from database import Base

class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    password = Column(String, nullable=False)
    profile = Column(String, nullable=False)  # admin_profile u operador_profile

class Dispositivo(Base):
    __tablename__ = "dispositivos"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    address = Column(String, nullable=False)  # IP o Subred (ej. 10.1.7.52 o 10.1.7.0/24)
    key = Column(String, nullable=False)

class PoliticaComando(Base):
    __tablename__ = "politicas_comando"

    id = Column(Integer, primary_key=True, index=True)
    profile = Column(String, nullable=False)  # admin_profile o operador_profile
    command = Column(String, nullable=False)  # Comando restringido (ej. "reload")
    action = Column(String, default="deny")  # deny o permit
