from datetime import datetime


def get_int_timestamp():
    return int(datetime.now().timestamp() * 1000000)