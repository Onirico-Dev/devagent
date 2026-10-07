def dividir(a, b):
    try:
        return a / b
    except ZeroDivisionError:
        return 0
