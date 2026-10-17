"""IRCTC URLs, selector fallbacks and label maps.

IRCTC is an Angular SPA and its DOM changes over time. Every step therefore
uses a *list* of selector fallbacks plus text/role-based locators. If IRCTC
changes their markup, update the lists here (and please send a PR!).
Selectors below were written against the ng-et (new) IRCTC site 2024-2026.
"""

HOME_URL = "https://www.irctc.co.in/nget/train-search"
TRAIN_SEARCH_URL = "https://www.irctc.co.in/nget/train-search"
BOOKING_HISTORY_URL = "https://www.irctc.co.in/nget/booking-history"
TDR_URL = "https://www.irctc.co.in/nget/tdr"

# ---- login modal ----
LOGIN_BUTTON = [
    "a:has-text('LOGIN')",
    "button:has-text('LOGIN')",
    "text=LOGIN",
]
LOGIN_MODAL = [
    "app-login",
    "p-dialog div.ui-dialog",
    ".login-modal",
]
USERNAME_INPUT = [
    "input[formcontrolname='userid']",
    "input[formcontrolname='userName']",
    "input#username",
    "input[placeholder*='User' i]",
    "input[type='text']:near(text=Username)",
]
PASSWORD_INPUT = [
    "input[formcontrolname='password']",
    "input#password",
    "input[type='password']",
]
CAPTCHA_IMG = [
    "app-login img.captcha-img",
    "app-login img[src*='captcha']",
    "img.captcha-img",
    "img#captchaImg",
    "img[src*='captcha' i]",
]
CAPTCHA_REFRESH = [
    "app-login a:has-text('Try Another')",
    "button:has-text('Try Another')",
    "text=Try Another",
    "app-login .fa-refresh",
    "button[aria-label*='refresh' i]",
]
CAPTCHA_INPUT = [
    "app-login input[formcontrolname='captcha']",
    "input[formcontrolname='captcha']",
    "input[formcontrolname='captchaInput']",
    "input[placeholder*='captcha' i]",
]
LOGIN_SUBMIT = [
    "app-login button:has-text('SIGN IN')",
    "button:has-text('SIGN IN')",
    "app-login button[type='submit']",
]
LOGIN_ERROR = [
    ".ui-toast-message",
    "p-toastitem .ui-toast-message",
    ".error",
    "text=/Invalid.*[Cc]aptcha/",
    "text=/Invalid Credentials/",
]
LOGGED_IN_MARKERS = [
    "a:has-text('LOGOUT')",
    "button:has-text('LOGOUT')",
    "text=My Account",
    "text=My Profile",
]

# ---- train search form ----
FROM_INPUT = [
    "p-autocomplete#origin input",
    "input[aria-label*='From' i]",
    "#origin input",
    "input[placeholder*='From' i]",
]
TO_INPUT = [
    "p-autocomplete#destination input",
    "input[aria-label*='To' i]",
    "#destination input",
    "input[placeholder*='To' i]",
]
AUTOCOMPLETE_OPTION = [
    "p-autocomplete li.ui-autocomplete-list-item",
    "ul.ui-autocomplete-items li",
    ".ui-autocomplete-list-item",
    "li[role='option']",
]
DATE_INPUT = [
    "p-calendar#journeyDate input",
    "#journeyDate input",
    "input[placeholder*='Journey Date' i]",
    "p-calendar input",
]
CLASS_DROPDOWN = [
    "#journeyClass",
    "p-dropdown#journeyClass",
    "div:has(> #journeyClass)",
]
QUOTA_DROPDOWN = [
    "#journeyQuota",
    "p-dropdown#journeyQuota",
]
DROPDOWN_ITEM = [
    "p-dropdownitem li",
    "li.ui-dropdown-item",
    ".ui-dropdown-items li",
]
SEARCH_BUTTON = [
    "button:has-text('Search')",
    "button[label='Search']",
    "text=Modify Search",
]

# ---- train list ----
TRAIN_ROWS = [
    "app-train-list div.train-list",
    ".train-list",
    "app-train-avl-enq",
]
AVAILABLE_CELL = "text=/AVAILABLE|AVL|RAC|WL\\d+/i"
BOOK_NOW_BUTTON = [
    "button:has-text('Book Now')",
    "input[value='Book Now']",
]

# ---- passenger details ----
PASSENGER_NAME = "input[formcontrolname='passengerName']"
PASSENGER_AGE = "input[formcontrolname='passengerAge']"
PASSENGER_GENDER = "select[formcontrolname='passengerGender']"
PASSENGER_BERTH = "select[formcontrolname='passengerBerthChoice']"
PASSENGER_FOOD = "select[formcontrolname='passengerFoodChoice']"
PASSENGER_ID_TYPE = "select[formcontrolname='passengerIdCardType']"
PASSENGER_ID_NO = "input[formcontrolname='passengerIdCardNo']"
ADD_PASSENGER = [
    "a:has-text('+ Add Passenger')",
    "button:has-text('Add Passenger')",
    "text=+ Add Passenger",
]
MOBILE_INPUT = [
    "input[formcontrolname='mobileNumber']",
    "input#mobileNumber",
    "input[formcontrolname='mobile']",
]
AUTO_UPGRADE_CHECK = [
    "input#autoUpgrade",
    "p-checkbox[label*='Auto Upgradation' i] input",
    "text=Consider for Auto Upgradation",
]
CONFIRM_BERTH_CHECK = [
    "input#confirmBerths",
    "p-checkbox[label*='Book only if confirm berths' i] input",
]
INSURANCE_YES = [
    "input[name='travelInsurance'][value='Yes']",
    "p-radiobutton[label='Yes']",
]
CONTINUE_BUTTON = [
    "button:has-text('Continue')",
    "button:has-text('Submit')",
]
REVIEW_CAPTCHA_IMG = [
    "app-review-journey img.captcha-img",
    "app-passenger-input img.captcha-img",
    "img.captcha-img",
]
REVIEW_CAPTCHA_INPUT = [
    "app-review-journey input[formcontrolname='captcha']",
    "input[formcontrolname='captcha']",
]

# ---- payment ----
UPI_TAB = [
    "text=BHIM/UPI",
    "text=UPI",
    "p-tabview li:has-text('UPI')",
]
UPI_ID_INPUT = [
    "input[placeholder*='UPI' i]",
    "input[formcontrolname='upiId']",
]
PAY_BUTTON = [
    "button:has-text('Pay')",
    "button:has-text('Make Payment')",
    "button:has-text('Proceed')",
]

# Dropdown visible labels on IRCTC (used for text matching)
CLASS_LABELS = {
    "1A": "AC First Class (1A)",
    "2A": "AC 2 Tier (2A)",
    "3A": "AC 3 Tier (3A)",
    "3E": "AC 3 Economy (3E)",
    "CC": "AC Chair car (CC)",
    "EC": "Exec. Chair Car (EC)",
    "SL": "Sleeper (SL)",
    "2S": "Second Sitting (2S)",
    "EA": "Anubhuti Class (EA)",
    "FC": "First Class (FC)",
}
QUOTA_LABELS = {
    "GN": "General",
    "TQ": "Tatkal",
    "PT": "Premium Tatkal",
    "LD": "Ladies",
    "HO": "Headquarters",
    "DF": "Defence",
    "PH": "Parliament House",
    "YU": "Yuva",
    "SS": "Senior Citizen",
    "DP": "Duty Pass",
}
GENDER_LABELS = {"M": "Male", "F": "Female", "T": "Transgender"}
BERTH_LABELS = {
    "LB": "Lower",
    "MB": "Middle",
    "UB": "Upper",
    "SL": "Side Lower",
    "SU": "Side Upper",
    "WS": "Window Side",
    "CB": "Cabin",
    "CP": "Coupe",
    "SM": "Side Middle",
    "NP": "No Preference",
}
FOOD_LABELS = {"VEG": "Veg", "NON VEG": "Non Veg", "NO FOOD": "No Food"}

INVALID_CAPTCHA_TEXT = ("nvalid captcha", "ncorrect captcha", "aptcha")
INVALID_CREDENTIALS_TEXT = ("nvalid credentials", "nvalid login", "ncorrect password")
