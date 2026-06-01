import numpy as np


def safe_divide(a, b):
    return np.divide(a, b, out=np.zeros_like(a, dtype=float), where=b != 0)


def ndvi(nir, red):
    return safe_divide(nir - red, nir + red)


def ndmi(nir, swir):
    """Normalised Difference Moisture Index."""
    return safe_divide(nir - swir, nir + swir)


def evi(nir, red, blue):
    return 2.5 * safe_divide(nir - red, nir + 6 * red - 7.5 * blue + 1)


def evi2(nir, red):
    return 2.4 * safe_divide(nir - red, nir + red + 1)


def savi(nir, red, l=0.5):
    return (1 + l) * safe_divide(nir - red, nir + red + l)


def osavi(nir, red):
    return 1.16 * safe_divide(nir - red, nir + red + 0.16)


def msavi(nir, red):
    term = (2 * nir + 1) ** 2 - 8 * (nir - red)
    term = np.clip(term, 0, None)
    return (2 * nir + 1 - np.sqrt(term)) / 2


def rdvi(nir, red):
    return safe_divide(nir - red, np.sqrt(nir + red))


def ipvi(nir, red):
    return safe_divide(nir, nir + red)


def dvi(nir, red):
    return nir - red


def rvi(nir, red):
    return safe_divide(nir, red)


def ndwi(green, nir):
    return safe_divide(green - nir, green + nir)


def wbi(r970, r900):
    return safe_divide(r970, r900)


def nli(nir, red):
    return safe_divide(nir ** 2 - red, nir ** 2 + red)


def gndvi(nir, green):
    return safe_divide(nir - green, nir + green)


def sipi(r800, r445, r680):
    return safe_divide(r800 - r445, r800 - r680)


def cvi(nir, red, green):
    return safe_divide(nir * red, green ** 2)


def mcari(r700, r670, r550):
    return ((r700 - r670) - 0.2 * (r700 - r550)) * safe_divide(r700, r670)


def arvi(nir, red, blue, y=0.08):
    red_corr = red - y * (red - blue)
    return safe_divide(nir - red_corr, nir + red_corr)


def arvi2(nir, red):
    return -0.18 + 1.17 * safe_divide(nir - red, nir + red)


def atsavi(nir, red, a=1.0, b=0.0, x=0.08):
    num = a * (nir - red) - b
    den = a * nir + red - a * b + x * (1 + a ** 2)
    return safe_divide(num, den)


def wdvi(nir, red, a=1.0):
    return nir - a * red


def wdrvi(nir, red, alpha=0.1):
    return safe_divide(alpha * nir - red, alpha * nir + red)


def gli(green, red, blue):
    return safe_divide(2 * green - red - blue, 2 * green + red + blue)


def ngrdi(green, red):
    return safe_divide(green - red, green + red)


def vari(green, red, blue):
    return safe_divide(green - red, green + red - blue)


def gemi(nir, red):
    n = safe_divide(2 * (nir ** 2 - red ** 2) + 1.5 * nir + 0.5 * red, nir + red + 0.5)
    return safe_divide(n * (1 - 0.25 * n) - (red - 0.125), 1 - red)


def mtvi2(r800, r550, r670):
    numerator = 1.5 * (1.2 * (r800 - r550) - 2.5 * (r670 - r550))
    inner = (2 * r800 + 1) ** 2 - (6 * r800 - 5 * np.sqrt(np.clip(r670, 0, None))) - 0.5
    inner = np.clip(inner, 1e-6, None)
    return safe_divide(numerator, np.sqrt(inner))


def tvi(r750, r550, r670):
    return 0.5 * (120 * (r750 - r550) - 200 * (r670 - r550))


def tndvi(nir, red):
    base = safe_divide(nir - red, nir + red)
    base = np.clip(base, 0, None)
    return np.sqrt(base) + 0.5


def log_ratio(nir, red):
    return np.log(safe_divide(nir, red))


def single_band(band):
    return band
