from models import SessionLocal, Question, Base, engine

def main():
    Base.metadata.create_all(engine)  # garante que as tabelas existem
    db = SessionLocal()
    try:
        deleted = db.query(Question).delete()
        db.commit()
        print(f"✅ {deleted} perguntas removidas da tabela.")
    finally:
        db.close()

if __name__ == "__main__":
    main()
