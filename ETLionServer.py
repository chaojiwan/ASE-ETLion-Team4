import json
import random
import urllib2

from datetime import datetime
from json import dumps
from flask import request
from flask import render_template
from flask import redirect
from flask import session
from flask import url_for
from flask_mail import Mail
from flask_mail import Message
from flask_socketio import SocketIO
from sqlalchemy import exc

from AppUtil import init_app
from Enum import POST, GET
from Enum import QUERY_URL, ORDER_URL
from ETLionMail import get_email_html
from forms import SignupForm, LoginForm
from models import db, User, Order, Trade

app = init_app()

mail = Mail(app)

db.init_app(app)

socketio = SocketIO(app, async_mode="eventlet")
thread = None
is_order_canceled = False

# latest order/trade info
order = {}
trades = []

def send_email_notification(recipients, username):
    if not isinstance(recipients, list):
        recipients = [recipients]
    msg = Message("Your Order Complete Successfully.", recipients=recipients)
    msg.html = get_email_html(username)
    mail.send(msg)

def json_serial(obj):
    """
    JSON serializer for objects not serializable by default json code
    """
    if isinstance(obj, datetime):
        serial = obj.isoformat()
        return serial
    raise TypeError ("Type not serializable")

def background_thread_place_order(
        order_size, inventory, total_duration, start_datetime,
        recipients=[], username="",
        is_for_test=False, is_for_history_test=False
    ):
    order_discount = 10
    order_size = int(order_size)
    inventory = int(inventory)
    duration = int(total_duration)

    times = duration / (inventory / order_size)
    trading_freq = int(times)

    print "!!!!!!frequency: ", trading_freq

    # Start with all shares and no profit
    total_qty = qty = inventory
    pnl = 0
    # Repeat the strategy until we run out of shares.
    while qty > 0:
        global is_order_canceled
        if is_order_canceled:
            is_order_canceled = False
            break
        # Query the price once every N seconds.
        socketio.sleep(trading_freq)
        quote = json.loads(
            urllib2.urlopen(QUERY_URL.format(random.random())).read()
        )
        price = float(quote['top_bid']['price'])
        # Attempt to execute a sell order.
        discount_price = price - order_discount
        order_args = (order_size, discount_price)
        print "Executing 'sell' of {:,} @ {:,}".format(*order_args)
        url   = ORDER_URL.format(random.random(), *order_args)
        order = json.loads(urllib2.urlopen(url).read())

        # Update the PnL if the order was filled.
        timestamp = dumps(datetime.now(), default=json_serial)
        price    = order['avg_price']
        notional = int(price * order_size)
        if order['avg_price'] <= 0:
            print "Unfilled order; $%s total, %s qty" % (pnl, qty)
            print "order_discount", order_discount
            order_size = 0
            pnl = 0
            status = "fail"
            order_discount += 1
        else:
            pnl += notional
            qty -= order_size
            order_size = order_size if qty > 0 else qty + order_size
            print "Sold {:,} for ${:,}/share, ${:,} notional, ${:,} qty left".format(
                order_size, price, notional, qty
            )
            status = "success"

        emit_params = {
            'order_size': order_size,
            'discount_price': discount_price,
            'share_price': price,
            'notional': notional,
            'pnl': pnl,
            'total_qty': total_qty,
            'timestamp': timestamp,
            'status': status
        }
        print emit_params
        trades.append(emit_params)
        socketio.emit('trade_log', emit_params)

    socketio.emit('trade_over', "trade is over")

    if not is_for_test:
        with app.app_context():
            send_email_notification(recipients, username)
            save_order(recipients, 'completed' if qty == 0 else 'interrupted')

def exec_cancel_order():
    global is_order_canceled
    is_order_canceled = True

def exec_resume_order():
    global is_order_canceled
    is_order_canceled = False

@socketio.on('connect')
def test_connect():
    print "Connected with Socket-IO !!!!!!!!!!!!!!!!!!!!!!!"

@socketio.on('disconnect')
def test_disconnect():
    print 'Client disconnected', request.sid

@socketio.on('calculate')
def calculate(post_params):
    #clear last order detail
    global trades
    global order
    trades = []
    order = post_params

    exec_resume_order()

    print "calculate", post_params

    if (post_params.get("is_for_test")
        or post_params.get("is_for_history_test")):
        background_thread_place_order(**post_params)

    else:
        global thread
        post_params['recipients'] = session['email']
        post_params['username'] = session['username']
        thread = socketio.start_background_task(
            target=background_thread_place_order, **post_params
        )

def is_user_in_session():
    return ('email' in session and 'username' in session)

@app.route('/')
@app.route('/index')
def index():
    form = LoginForm(request.form)
    if is_user_in_session():
        return redirect(url_for('trade', username=session['username']))
    else:
        return render_template(
            "index.html",async_mode=socketio.async_mode, form=form
        )

@socketio.on('cancel_order')
def cancel(post_params={}):
    exec_cancel_order()
    if post_params and post_params.get('is_for_test'):
        emit_params = {"is_order_canceled": is_order_canceled}
        socketio.emit('cancel_order', emit_params)

@app.route('/trade')
def trade():
    if not is_user_in_session():
        return redirect(url_for('index', username=session['username']))
    else:
        return render_template(
            "trade.html",
            async_mode=socketio.async_mode,
            username=session['username']
        )

@app.route("/signup", methods=[GET, POST])
def signup():
    exec_resume_order()

    if is_user_in_session():
        return redirect(url_for('trade', username=session['username']))

    form = SignupForm(request.form)

    try:
        if request.method == POST:
            if not form.validate():
                return render_template('signup.html', form=form)
            else:
                newuser = User(
                    form.firstname.data,
                    form.lastname.data,
                    form.email.data,
                    form.password.data
                )
                db.session.add(newuser)
                db.session.commit()

                session['email'] = newuser.email
                session['username'] = newuser.firstname + ' ' + newuser.lastname
                return redirect(url_for('index', username=session['username']))

        elif request.method == GET:
            return render_template('signup.html', form=form)

    except exc.IntegrityError:
        return render_template('signup.html', form=form, duplicateEmailMsg = "User email alrealy exist.")


def date_handler(obj):
    return obj.isoformat() if hasattr(obj, 'isoformat') else obj

def get_all_order(user_email):
    user = User.query.filter_by(email=user_email).first()
    orders = Order.query.filter_by(uid=user.uid).all()

    all_orders = {}
    all_orders['orders'] = []
    for order in orders:
        order_detail = {}
        order_detail['trades'] = []
        order_detail['type'] = order.type
        order_detail['size'] = order.size
        order_detail['inventory'] = order.inventory
        order_detail['timestamp'] = json.dumps(order.timestamp, default=date_handler)
        order_detail['final_status'] = order.final_status

        trades = Trade.query.filter_by(oid=order.oid).all()

        # ignore empty trades
        if len(trades) == 0:
            continue

        for trade in trades:
            trade_detail = {}
            trade_detail['tid'] = trade.tid
            trade_detail['type'] = trade.type
            trade_detail['price'] = trade.price
            trade_detail['shares'] = trade.shares
            trade_detail['notional'] = trade.notional
            trade_detail['status'] = trade.status
            trade_detail['timestamp'] = json.dumps(trade.timestamp, default=date_handler)

            order_detail['trades'].append(trade_detail)

        all_orders['orders'].append(order_detail)

    return json.dumps(all_orders)


@app.route("/history", methods=[GET, POST])
def history():
    if not is_user_in_session():
        return redirect(url_for('index', username=session['username']))
    else:
        email = session['email']
        return render_template(
            "history.html",
            async_mode=socketio.async_mode,
            username=session['username'],
            all_orders=get_all_order(email)
        )

def getOrderSqlTimeStamp(datetime_str):
    date_time = datetime.strptime(datetime_str, "%m/%d/%Y %I:%M:%S %p")
    formated_time = '{0:%Y}-{0:%m}-{0:%d} {0:%H}:{0:%M}:{0:%S}'.format(date_time)
    return formated_time


def getTradeSqlTimestamp(json_timestamp):
    date_time = datetime.strptime(json_timestamp, '"%Y-%m-%dT%H:%M:%S.%f"')
    formated_time = '{0:%Y}-{0:%m}-{0:%d} {0:%H}:{0:%M}:{0:%S}'.format(date_time)
    return formated_time


def save_order(user_email, order_status):
    global order
    global trades

    user = User.query.filter_by(email=user_email).first()
    new_order = Order(
        'sell',
        order['order_size'],
        order['inventory'],
        user.uid,
        getOrderSqlTimeStamp(order['start_datetime']),
        order_status
    )
    db.session.add(new_order)
    db.session.commit()

    for trade in trades:
        newTrade = Trade(
            'sell',
            trade['share_price'],
            trade['order_size'],
            trade['notional'],
            trade['status'],
            new_order.oid,
            getTradeSqlTimestamp(trade['timestamp'])
        )
        db.session.add(newTrade)
        db.session.commit()


@app.route("/login", methods=[GET, POST])
def login():
    exec_resume_order()

    if is_user_in_session():
        return redirect(url_for('trade', username=session['username']))

    form = LoginForm(request.form)

    if request.method == POST:
        email = form.email.data
        password = form.password.data
        user = User.query.filter_by(email=email).first()
        if user is not None and user.check_password(password):
            session['email'] = user.email
            session['username'] = user.firstname + ' ' + user.lastname
            return redirect(url_for('trade', username=session['username']))
        else:
            return redirect(url_for('index'))

@app.route("/logout")
def logout():
    session.pop('email', None)
    session.pop('username', None)
    exec_cancel_order()
    return redirect('/')

if __name__ == "__main__":
    import click

    @click.command()
    @click.argument('HOST', default='127.0.0.1')
    @click.argument('PORT', default=4156, type=int)
    def socketio_app_run(host, port):
        try:
            HOST, PORT = host, port
            print "ET Lion Server Running On %s:%d" % (HOST, PORT)
            socketio.run(app, host=HOST, port=PORT, debug=True)
        except KeyboardInterrupt:
            print "Ctrl-c received! Sending kill to threads..."
            socketio.stop()

    socketio_app_run()
