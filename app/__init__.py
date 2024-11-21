import os
from datetime import datetime

from dotenv import load_dotenv
from flask import Flask, render_template, redirect, url_for, flash, request
from flask_bootstrap import Bootstrap
from flask_login import LoginManager, login_user, current_user, login_required, logout_user
from itsdangerous import URLSafeTimedSerializer
from werkzeug.security import generate_password_hash, check_password_hash

from app.admin.routes import admin
from app.db_models import db, User, Item, Ordered_item, Order
from app.forms import LoginForm, RegisterForm
from app.funcs import mail, send_confirmation_email, fulfill_order

load_dotenv()
app = Flask(__name__)
app.register_blueprint(admin)

app.config["SECRET_KEY"] = os.environ["SECRET_KEY"]
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ["DB_URI"]
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAIL_USERNAME'] = os.environ["EMAIL"]
app.config['MAIL_PASSWORD'] = os.environ["PASSWORD"]
app.config['MAIL_SERVER'] = "smtp.googlemail.com"
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_PORT'] = 587

Bootstrap(app)
db.init_app(app)
mail.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)

with app.app_context():
    db.create_all()


@app.context_processor
def inject_now():
    """ sends datetime to templates as 'now' """
    return {'now': datetime.utcnow()}


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(user_id)


@app.route("/")
def home():
    items = Item.query.all()
    return render_template("home.html", items=items)


@app.route("/login", methods=['POST', 'GET'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    form = LoginForm()
    if form.validate_on_submit():
        email = form.email.data
        user = User.query.filter_by(email=email).first()
        if user is None:
            flash(f'User with email {email} doesn\'t exist!<br> <a href={url_for("register")}>Register now!</a>',
                  'error')
            return redirect(url_for('login'))
        elif check_password_hash(user.password, form.password.data):
            login_user(user)
            return redirect(url_for('home'))
        else:
            flash("Email and password incorrect!!", "error")
            return redirect(url_for('login'))
    return render_template("login.html", form=form)


@app.route("/register", methods=['POST', 'GET'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    form = RegisterForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user:
            flash(f"User with email {user.email} already exists!!<br> <a href={url_for('login')}>Login now!</a>",
                  "error")
            return redirect(url_for('register'))
        new_user = User(name=form.name.data,
                        email=form.email.data,
                        password=generate_password_hash(
                            form.password.data,
                            method='pbkdf2:sha256',
                            salt_length=8),
                        phone=form.phone.data)
        db.session.add(new_user)
        db.session.commit()
        # send_confirmation_email(new_user.email)
        flash('Thanks for registering! You may login now.', 'success')
        return redirect(url_for('login'))
    return render_template("register.html", form=form)


@app.route("/checkout", methods=["GET", "POST"])
@login_required
def checkout():
    if request.method == "POST":
        new_order = orders(uid=current_user.id)
        db.session.add(new_order)
        db.session.commit()
        flash("Order placed successfully. Cash on Delivery selected.", "success")
        return redirect(url_for("orders"))
    return render_template("checkout.html")


@app.route('/confirm/<token>')
def confirm_email(token):
    try:
        confirm_serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])
        email = confirm_serializer.loads(token, salt='email-confirmation-salt', max_age=3600)
    except:
        flash('The confirmation link is invalid or has expired.', 'error')
        return redirect(url_for('login'))
    user = User.query.filter_by(email=email).first()
    if user.email_confirmed:
        flash(f'Account already confirmed. Please login.', 'success')
    else:
        user.email_confirmed = True
        db.session.add(user)
        db.session.commit()
        flash('Email address successfully confirmed!', 'success')
    return redirect(url_for('login'))


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


@app.route("/resend")
@login_required
def resend():
    send_confirmation_email(current_user.email)
    logout_user()
    flash('Confirmation email sent successfully.', 'success')
    return redirect(url_for('login'))


@app.route("/add/<id>", methods=['POST'])
def add_to_cart(id):
    if not current_user.is_authenticated:
        flash(f'You must login first!<br> <a href={url_for("login")}>Login now!</a>', 'error')
        return redirect(url_for('login'))

    item = Item.query.get(id)
    if request.method == "POST":
        quantity = request.form["quantity"]
        current_user.add_to_cart(id, quantity)
        flash(
            f'''{item.name} successfully added to the <a href=cart>cart</a>.<br> <a href={url_for("cart")}>view cart!</a>''',
            'success')
        return redirect(url_for('home'))


@app.route("/cart")
@login_required
def cart():
    price = 0
    price_ids = []
    items = []
    quantity = []
    for cart in current_user.cart:
        items.append(cart.item)
        quantity.append(cart.quantity)
        price_id_dict = {
            "price": cart.item.price_id,
            "quantity": cart.quantity,
        }
        price_ids.append(price_id_dict)
        price += cart.item.price * cart.quantity
    return render_template('cart.html', items=items, price=price, price_ids=price_ids, quantity=quantity)


@app.route('/orders')
@login_required
def orders():
    return render_template('orders.html', orders=current_user.orders)


@app.route("/remove/<id>/<quantity>")
@login_required
def remove(id, quantity):
    current_user.remove_from_cart(id, quantity)
    return redirect(url_for('cart'))


@app.route('/item/<int:id>')
def item(id):
    item = Item.query.get(id)
    return render_template('item.html', item=item)


@app.route('/search')
def search():
    query = request.args['query']
    search = "%{}%".format(query)
    items = Item.query.filter(Item.name.like(search)).all()
    return render_template('home.html', items=items, search=True, query=query)


# stripe stuffs
@app.route('/payment_success')
def payment_success():
    return render_template('success.html')


@app.route('/payment_failure')
def payment_failure():
    return render_template('failure.html')


@app.route('/place_order', methods=['POST'])
@login_required
def place_order():
    if not current_user.cart:
        flash("Your cart is empty. Please add items to your cart before placing an order.", "error")
        return redirect(url_for('cart'))

    try:
        # Create a new order
        new_order = Order(
            uid=current_user.id,
            date=datetime.utcnow(),
            status="Pending"
        )
        db.session.add(new_order)
        db.session.commit()  # Commit to get the order ID

        # Move items from cart to Ordered_item
        for cart_item in current_user.cart:
            ordered_item = Ordered_item(
                oid=new_order.id,
                itemid=cart_item.itemid,
                quantity=cart_item.quantity
            )
            db.session.add(ordered_item)
            db.session.delete(cart_item)  # Remove the item from the cart

        db.session.commit()  # Commit all changes
        flash("Order placed successfully! Cash on Delivery selected.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"An error occurred while placing the order: {e}", "error")
        return redirect(url_for('cart'))

    return redirect(url_for('orders'))
