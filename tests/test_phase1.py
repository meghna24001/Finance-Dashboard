"""Checks the database tables: each user only sees their own data, passwords are hashed.
Uses a throwaway in-memory database, so your real data is never touched."""
from app import create_app
from config import TestConfig
from models import db, User, Category, Transaction

app = create_app(TestConfig)

with app.app_context():
    a = User(email="a@example.com", name="Asha"); a.set_password("secret123")
    b = User(email="b@example.com", name="Ben");  b.set_password("other456")
    db.session.add_all([a, b]); db.session.commit()

    food = Category(name="Food", type="expense", user_id=a.id)
    db.session.add(food); db.session.commit()

    db.session.add_all([
        Transaction(amount=250.50, type="expense", description="Lunch", user_id=a.id, category_id=food.id),
        Transaction(amount=50000, type="income", description="Stipend", user_id=a.id),
        Transaction(amount=99, type="expense", description="Ben's coffee", user_id=b.id),
    ])
    db.session.commit()

    print("Asha's transactions:", Transaction.query.filter_by(user_id=a.id).all())
    print("Ben's transactions: ", Transaction.query.filter_by(user_id=b.id).all())
    print("Password hash stored (not plain):", a.password_hash[:25] + "...")
    print("Right password ok:", a.check_password("secret123"), "| wrong password ok:", a.check_password("nope"))

    try:
        dup = User(email="a@example.com", name="Dup"); dup.set_password("x")
        db.session.add(dup); db.session.commit()
    except Exception as e:
        db.session.rollback()
        print("Duplicate email blocked:", type(e).__name__)
