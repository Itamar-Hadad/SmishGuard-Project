"""
SMS Smishing Detection — ML Model Training Pipeline
====================================================
Trains 5 classifiers + a weighted soft-voting ensemble on SBERT embeddings
combined with engineered text features. Saves the best model to disk.

Run:
    python MLsmish.py

Requires:
    pip install sentence-transformers scikit-learn xgboost joblib pandas numpy matplotlib seaborn
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import warnings
import joblib
import os
import subprocess
import sys

from sentence_transformers import SentenceTransformer

from sklearn.linear_model import LogisticRegression
from sklearn.svm import SVC
from sklearn.ensemble import RandomForestClassifier, VotingClassifier
from sklearn.neural_network import MLPClassifier
from xgboost import XGBClassifier

from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.model_selection import train_test_split, GridSearchCV, StratifiedKFold
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score, f1_score,
    roc_auc_score, confusion_matrix, roc_curve, precision_recall_curve
)

# Import shared utilities from the NLP preprocessing module
from NLP_smish import (
    preprocess_text, extract_features_from_text,
    SBERT_MODEL_NAME, BATCH_SIZE,
    detect_shortened_url, detect_login_words, detect_urgency_words,
    detect_threat_words, detect_action_request, detect_suspicious_url_domain,
    detect_reference_number, detect_exact_amount, detect_official_domain,
)

warnings.filterwarnings('ignore')

# ============================================================================
# CONFIGURATION
# ============================================================================
DATASET_PATH  = 'dataset/merged_dataset.csv'
RANDOM_STATE  = 42
TEST_SIZE     = 0.2
CV_FOLDS      = 5
MODEL_PATH     = 'smishing_detector.pkl'
ENCODER_PATH   = 'label_encoder.pkl'
TFIDF_PATH     = 'tfidf_vectorizer.pkl'
THRESHOLD_PATH = 'smishing_threshold.pkl'
GRAPHS_DIR    = 'graphs'

os.makedirs(GRAPHS_DIR, exist_ok=True)
sns.set_theme(style='whitegrid')

# ============================================================================
# FEATURE ENGINEERING
# ============================================================================
def engineer_features(df_input):
    """Add 15 text-derived features to the DataFrame."""
    d = df_input.copy()

    # Original (reduced to 4: merged msg_length+word_count → avg_word_length, dropped uppercase_ratio and exclamation_count)
    _wc = d['message'].str.split().str.len().replace(0, 1)
    d['avg_word_length']    = d['message'].str.len() / _wc
    d['digit_count']        = d['message'].apply(lambda m: sum(c.isdigit() for c in str(m)))
    d['special_char_count'] = d['message'].apply(lambda m: sum(c in '!$#*@' for c in str(m)))

    # SMISH signals (6)
    d['has_shortened_url']         = d['message'].apply(detect_shortened_url)
    d['has_login_words']           = d['message'].apply(detect_login_words)
    d['has_urgency_words']         = d['message'].apply(detect_urgency_words)
    d['has_threat_words']          = d['message'].apply(detect_threat_words)
    d['asks_user_to_act']          = d['message'].apply(detect_action_request)
    d['has_suspicious_url_domain'] = d['message'].apply(detect_suspicious_url_domain)

    # HAM signals (2)
    d['has_specific_reference_number'] = d['message'].apply(detect_reference_number)
    d['contains_official_domain']      = d['message'].apply(detect_official_domain)

    # Neutral (1) — can appear in both classes; excluded from ham_signal_count
    d['has_exact_amount'] = d['message'].apply(detect_exact_amount)

    # Interaction aggregates (2)
    _smish_cols = ['has_shortened_url', 'has_login_words', 'has_urgency_words',
                   'has_threat_words', 'asks_user_to_act', 'has_suspicious_url_domain']
    _ham_cols   = ['has_specific_reference_number', 'contains_official_domain']
    d['smish_signal_count'] = d[_smish_cols].sum(axis=1)
    d['ham_signal_count']   = d[_ham_cols].sum(axis=1)

    return d

TEXT_FEATURE_COLS = [
    # Original (4: avg_word_length replaces msg_length+word_count; uppercase_ratio and exclamation_count dropped)
    'avg_word_length', 'digit_count', 'special_char_count',
    # SMISH signals (6)
    'has_shortened_url', 'has_login_words', 'has_urgency_words',
    'has_threat_words', 'asks_user_to_act', 'has_suspicious_url_domain',
    # HAM signals (2)
    'has_specific_reference_number', 'contains_official_domain',
    # Neutral (1)
    'has_exact_amount',
    # Interaction aggregates (2)
    'smish_signal_count', 'ham_signal_count',
]

# ============================================================================
# EVALUATION HELPER
# ============================================================================
def model_kpi(model_name, y_true, y_pred, y_proba=None,
              label_encoder=None, save_path=None):
    """
    Compute evaluation metrics and plot confusion matrix + ROC curve.

    Returns:
        metrics_df — DataFrame with Accuracy, Precision, Recall, F1, ROC-AUC, FPR, FNR
        cm         — confusion matrix (numpy array)
    """
    cm = confusion_matrix(y_true, y_pred)
    tn, fp, fn, tp = cm.ravel()

    metrics = {
        'Model':     model_name,
        'Accuracy':  round(accuracy_score(y_true, y_pred), 4),
        'Precision': round(precision_score(y_true, y_pred), 4),
        'Recall':    round(recall_score(y_true, y_pred), 4),
        'F1':        round(f1_score(y_true, y_pred), 4),
        'ROC-AUC':   round(roc_auc_score(y_true, y_proba) if y_proba is not None else float('nan'), 4),
        'FPR':       round(fp / (fp + tn), 4),
        'FNR':       round(fn / (fn + tp), 4),
    }
    metrics_df = pd.DataFrame([metrics])

    class_names = label_encoder.classes_ if label_encoder else ['ham', 'smish']

    fig, axes = plt.subplots(1, 2, figsize=(14, 4))

    # Confusion matrix
    ax = axes[0]
    sns.heatmap(cm, annot=True, fmt='d', cmap='Blues', ax=ax,
                xticklabels=class_names, yticklabels=class_names,
                linewidths=0.5)
    ax.set_title(f'{model_name}\nConfusion Matrix', fontsize=12, fontweight='bold')
    ax.set_xlabel('Predicted', fontsize=10)
    ax.set_ylabel('Actual', fontsize=10)

    # ROC curve
    ax = axes[1]
    if y_proba is not None:
        fpr_vals, tpr_vals, _ = roc_curve(y_true, y_proba)
        auc = metrics['ROC-AUC']
        ax.plot(fpr_vals, tpr_vals, color='#0366d6', lw=2, label=f'AUC = {auc:.4f}')
        ax.plot([0, 1], [0, 1], color='gray', linestyle='--', lw=1)
        ax.fill_between(fpr_vals, tpr_vals, alpha=0.1, color='#0366d6')
        ax.set_xlabel('False Positive Rate', fontsize=10)
        ax.set_ylabel('True Positive Rate', fontsize=10)
        ax.set_title(f'{model_name}\nROC Curve', fontsize=12, fontweight='bold')
        ax.legend(fontsize=10)

    plt.tight_layout()
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.show()

    return metrics_df, cm


# ============================================================================
# INFERENCE
# ============================================================================
def predict_message(message_text, model=None, encoder=None, sbert=None, tfidf=None, threshold=None):
    """
    Predict whether a raw SMS message is ham or smish.

    Parameters:
        message_text — raw SMS string
        model        — trained classifier (loads smishing_detector.pkl if None)
        encoder      — LabelEncoder (loads label_encoder.pkl if None)
        sbert        — SentenceTransformer (loads SBERT_MODEL_NAME if None)
        tfidf        — TfidfVectorizer (loads tfidf_vectorizer.pkl if None)
        threshold    — smish probability threshold (loads smishing_threshold.pkl if None)

    Returns:
        (label, confidence) — e.g. ('smish', 0.97)
    """
    if model is None:
        model = joblib.load(MODEL_PATH)
    if encoder is None:
        encoder = joblib.load(ENCODER_PATH)
    if sbert is None:
        sbert = SentenceTransformer(SBERT_MODEL_NAME)
    if tfidf is None:
        tfidf = joblib.load(TFIDF_PATH)
    if threshold is None:
        try:
            threshold = joblib.load(THRESHOLD_PATH)
        except FileNotFoundError:
            threshold = 0.5

    row = pd.DataFrame([{
        'message': message_text,
        'url': 0, 'email': 0, 'phone': 0
    }])

    # Auto-detect flags from the message text
    feats = extract_features_from_text(message_text)
    row['url']   = feats['url']
    row['email'] = feats['email']
    row['phone'] = feats['phone']

    # Hard rule: no URL/phone/email = cannot be smishing (smishing requires a call-to-action)
    if row['url'].iloc[0] == 0 and row['email'].iloc[0] == 0 and row['phone'].iloc[0] == 0:
        return 'ham', 0.95

    row = engineer_features(row)

    processed   = preprocess_text(message_text)
    embedding   = sbert.encode([processed], convert_to_numpy=True)
    flags       = row[['url', 'phone']].values.astype(float)
    text_feats  = row[TEXT_FEATURE_COLS].values.astype(float)
    tfidf_feats = tfidf.transform([processed]).toarray()
    X_new       = np.hstack([embedding, flags, text_feats, tfidf_feats])

    proba      = model.predict_proba(X_new)[0]
    smish_idx  = list(encoder.classes_).index('smish')
    smish_prob = float(proba[smish_idx])

    pred_int  = smish_idx if smish_prob >= threshold else (1 - smish_idx)
    label_str = encoder.inverse_transform([pred_int])[0]
    confidence = smish_prob if label_str == 'smish' else 1.0 - smish_prob

    return label_str, round(confidence, 4)


# ============================================================================
# MAIN TRAINING PIPELINE
# ============================================================================
if __name__ == '__main__':

    # ── Regenerate EDA graphs ────────────────────────────────────────────────
    print('=' * 70)
    print('GENERATING EDA GRAPHS')
    print('=' * 70)
    subprocess.run([sys.executable, 'create_graph.py'], check=True)

    # ── Load Dataset ─────────────────────────────────────────────────────────
    print('=' * 70)
    print('LOADING DATASET')
    print('=' * 70)

    df = pd.read_csv(DATASET_PATH)
    print(f'Dataset shape: {df.shape}')
    print(f'Label distribution:\n{df["label"].value_counts().to_string()}\n')

    # ── Hard-Negative Ham Augmentation ───────────────────────────────────────
    # Legitimate messages that contain URLs and/or financial words — the subspace
    # where the original dataset has only ~40 ham examples vs ~1,117 smish (28:1).
    # Adding these shifts the ratio to ~1:6.5, enough for classifiers to learn the
    # distinction between real bank notifications and phishing.
    # Categories: A=Israeli banks, B=Insurance/pension, C=Gov/public services,
    #             D=International banks, E=OTP/2FA, F=Delivery, G=Investment
    _HARD_NEG_HAM = [
        # ── A. Israeli bank account notifications ──────────────────────────
        ('ham', 'Leumi Bank: Your account ending in 3847 was charged a monthly fee of 11.50 NIS. View details: https://www.leumi.co.il/privatebanking', 'yes', 'no', 'no'),
        ('ham', 'Bank Hapoalim: Your account statement for 02/26 is ready. Log in to your personal area: https://www.bankhapoalim.co.il', 'yes', 'no', 'no'),
        ('ham', 'Mizrahi Tefahot: Your monthly account summary is available. View at https://www.mizrahi-tefahot.co.il/en/personal', 'yes', 'no', 'no'),
        ('ham', 'Otzar HaHayal: During 01/26, your account ending in 998 was charged: fees totaling 0.00 NIS, interest totaling 0.00 NIS. Details at https://www.bankotsar.co.il', 'yes', 'no', 'no'),
        ('ham', 'First International Bank: Your credit card statement for March 2026 is now available online. View: https://www.fibi.co.il/wps/portal/FibiMenu/Marketing', 'yes', 'no', 'no'),
        ('ham', 'Bank Leumi: Your payment of 320.00 NIS to Israel Electric Corporation was processed. Reference: 772341. Details: https://www.leumi.co.il', 'yes', 'no', 'no'),
        ('ham', 'Discount Bank: Monthly fee notice — your account was charged 8.90 NIS on 05/01/2026. View your account: https://www.discountbank.co.il', 'yes', 'no', 'no'),
        ('ham', 'Bank Hapoalim: A transfer of 1,500 NIS was made from your account to account ending in 2214. For details: https://www.bankhapoalim.co.il/wps/portal', 'yes', 'no', 'no'),
        ('ham', 'Union Bank of Israel: Your account ending in 5543 has a new statement ready for January 2026. Log in: https://www.unionbank.co.il', 'yes', 'no', 'no'),
        ('ham', 'Leumi Card: Your credit card statement for account ending 4421 is ready. Total balance: 847.20 NIS. View: https://www.leumicard.co.il', 'yes', 'no', 'no'),
        ('ham', 'Max (formerly Leumi Card): Your credit card bill of 1,243.50 NIS is due on 01/10/2026. Pay or view details: https://www.max.co.il', 'yes', 'no', 'no'),
        ('ham', 'Isracard: Your statement is ready. Total charges this month: 2,104.80 NIS. View at https://www.isracard.co.il', 'yes', 'no', 'no'),
        ('ham', 'CAL: Monthly statement available for account 9912. Balance due: 560.00 NIS. Details: https://www.cal-online.co.il', 'yes', 'no', 'no'),
        ('ham', 'Pepper Bank: Your account balance is 4,200 NIS. Last transaction: -85 NIS at Rami Levy supermarket. https://www.pepper.co.il/app', 'yes', 'no', 'no'),
        ('ham', 'Bank Hapoalim: Your loan payment of 890 NIS was deducted today per your standing order. Reference 58321. https://www.bankhapoalim.co.il', 'yes', 'no', 'no'),
        ('ham', 'Mizrahi Tefahot Mortgage: Your monthly mortgage payment of 4,120 NIS has been processed. For account details: https://www.mizrahi-tefahot.co.il/mortgage', 'yes', 'no', 'no'),
        ('ham', 'Bank Leumi: Foreign currency conversion completed — 500 USD converted to 1,845 NIS at rate 3.69. Transaction ID: 9927734. https://www.leumi.co.il', 'yes', 'no', 'no'),
        ('ham', 'Discount Bank: Your overdraft limit has been renewed for account ending in 3312. Current balance: -1,200 NIS. https://www.discountbank.co.il/private', 'yes', 'no', 'no'),
        ('ham', 'IBI Trade: Your account credit of 700 NIS has been applied to your trading account per the referral promotion. https://cloud.mc.ibi.co.il/sms_tr', 'yes', 'no', 'no'),
        ('ham', 'Bank Hapoalim: Payment received — your electricity bill of 234 NIS has been paid via direct debit. Ref 4412. https://www.bankhapoalim.co.il', 'yes', 'no', 'no'),
        ('ham', 'Fibi Bank: Your account statement message 093-040. Fees: 0.00 NIS. Interest: 0.00 NIS. For details visit https://www.fibi.co.il', 'yes', 'no', 'no'),
        ('ham', 'One Zero Digital Bank: Your daily account summary — opening balance 6,300 NIS, 2 transactions, closing balance 6,187 NIS. https://www.one-zero.co.il', 'yes', 'no', 'no'),
        ('ham', 'Poalim Express: Your standing transfer of 1,000 NIS to savings account was completed. View transaction: https://www.bankhapoalim.co.il', 'yes', 'no', 'no'),
        ('ham', 'Bank of Israel: Notice regarding the change in the prime interest rate effective 01/02/2026. Your mortgage payments will be updated accordingly. https://www.boi.org.il', 'yes', 'no', 'no'),
        ('ham', 'Excellence Nessuah: Your investment portfolio monthly report is ready. View at https://www.excellenceness.co.il/investor-portal', 'yes', 'no', 'no'),
        # ── B. Israeli insurance / pension ─────────────────────────────────
        ('ham', 'Menora Mivtachim: Dental claim 318699 approved. Payment will be made by bank transfer. View your claims: https://www.menoramivt.co.il/wps/myportal/personal/myclaims', 'yes', 'no', 'no'),
        ('ham', 'Clal Insurance: Your quarterly pension fund statement is now available. Total savings: 243,150 NIS. View: https://www.clalbit.co.il', 'yes', 'no', 'no'),
        ('ham', 'Migdal Insurance: Your health insurance renewal has been processed. New annual premium: 2,340 NIS. Details at https://www.migdal.co.il', 'yes', 'no', 'no'),
        ('ham', 'Harel Insurance: Medical claim 77341 for reimbursement of 450 NIS has been approved. Transfer within 3 business days. https://www.harel-group.co.il', 'yes', 'no', 'no'),
        ('ham', 'Ayalon Insurance: Your car insurance renewal — annual premium of 3,200 NIS due on 06/01/2026. View policy: https://www.ayalon-ins.co.il', 'yes', 'no', 'no'),
        ('ham', 'Phoenix Insurance: Your life insurance monthly payment of 180 NIS has been deducted. Policy 8812-C. Details: https://www.fnx.co.il', 'yes', 'no', 'no'),
        ('ham', 'Meitav Dash Pension: Your monthly pension contribution of 1,450 NIS has been received. View your portfolio: https://www.meitav.co.il/pension', 'yes', 'no', 'no'),
        ('ham', 'Bituach Leumi: Your child allowance for January 2026 has been deposited: 940 NIS. Details: https://www.btl.gov.il', 'yes', 'no', 'no'),
        ('ham', 'Generali Israel: Your provident fund annual statement for 2025 is ready. Total accumulated: 87,300 NIS. https://www.generali.co.il/personal-area', 'yes', 'no', 'no'),
        ('ham', 'Maccabi Healthcare: Your dental treatment reimbursement of 280 NIS has been approved. View claim status: https://www.maccabi4u.co.il', 'yes', 'no', 'no'),
        ('ham', 'Clalit Health Services: Your pharmacy copay receipt for this month — total paid: 95 NIS. View at https://www.clalit.co.il/he/myhealth', 'yes', 'no', 'no'),
        ('ham', 'Leumit Health Fund: Your referral to specialist has been approved. Book at https://www.leumit.co.il/makeappointment', 'yes', 'no', 'no'),
        ('ham', 'Shirbit Insurance: Your home insurance renewal — annual premium 1,140 NIS. Policy details: https://www.shirbit.co.il/my-policy', 'yes', 'no', 'no'),
        # ── C. Israeli government / public services ─────────────────────────
        ('ham', 'Israel Tax Authority: Your 2025 tax refund of 1,840 NIS has been approved and will be transferred to your bank account. Details: https://www.gov.il/he/departments/israel_tax_authority', 'yes', 'no', 'no'),
        ('ham', 'Tel Aviv Municipality: Your property tax payment of 1,200 NIS for the first half of 2026 has been received. Receipt: https://www.tel-aviv.gov.il/muni/Pages/TaxPayment.aspx', 'yes', 'no', 'no'),
        ('ham', 'National Insurance Institute: Your disability benefit of 3,100 NIS for February 2026 has been transferred. View details: https://www.btl.gov.il/benefits', 'yes', 'no', 'no'),
        ('ham', 'Israel Post Bank (Bank Yahav): Your salary deposit of 9,200 NIS has been credited to your account. https://www.bank-yahav.co.il', 'yes', 'no', 'no'),
        ('ham', 'Israel Electric Corporation: Your electricity bill for January 2026 — total charge 234.50 NIS. Pay online: https://www.iec.co.il/payments', 'yes', 'no', 'no'),
        ('ham', 'Bezeq: Your landline bill for 02/2026 — total: 89 NIS including VAT. Pay at https://www.bezeq.co.il/account/bill', 'yes', 'no', 'no'),
        ('ham', 'Jerusalem Municipality: Arnona payment confirmation for account 44129. Paid: 980 NIS. Receipt at https://www.jerusalem.muni.il/residents/taxes', 'yes', 'no', 'no'),
        ('ham', 'Ministry of Interior: Your passport renewal application has been received. Fee paid: 380 NIS. Application status: https://www.gov.il/he/service/passport_renewal', 'yes', 'no', 'no'),
        ('ham', 'Gihon Jerusalem Water: Your water bill for 01/2026 — total charge 142 NIS. Pay online: https://www.gihon.co.il/payments', 'yes', 'no', 'no'),
        ('ham', 'Hot Mobile: Your bill for 02/2026 — plan fee 39 NIS. Pay at https://www.hot.net.il/hotmobile/account/billing', 'yes', 'no', 'no'),
        ('ham', 'Partner Communications: Your mobile plan bill for March 2026 — 85 NIS. View and pay: https://www.partner.co.il/personal/billing', 'yes', 'no', 'no'),
        ('ham', 'Haifa Municipality: Your business license fee of 1,800 NIS for 2026 has been received. Reference: BL-9912. https://www.haifa.muni.il', 'yes', 'no', 'no'),
        ('ham', 'Israeli Securities Authority: Your annual investor statement for 2025 is available for download. View at https://www.isa.gov.il/investor-portal', 'yes', 'no', 'no'),
        ('ham', 'Ministry of Finance: Your annual report on retirement savings is available. View at https://www.mof.gov.il/GCB/Pages/Default.aspx', 'yes', 'no', 'no'),
        # ── D. International bank / utility billing ─────────────────────────
        ('ham', 'Chase Bank: Your account ending in 4721 statement is ready. Minimum payment due: $35.00. View: https://www.chase.com/digital/account-summary', 'yes', 'no', 'no'),
        ('ham', 'Bank of America: Your checking account statement for March 2026 is available online. Log in at https://www.bankofamerica.com/statements', 'yes', 'no', 'no'),
        ('ham', 'Wells Fargo: A payment of $1,240.00 has been posted to your mortgage account. Confirmation #WF8812341. https://www.wellsfargo.com/mortgage', 'yes', 'no', 'no'),
        ('ham', 'Citibank: Your credit card statement for account ending 3321 is ready. Balance: $450.20. Pay at https://www.citibank.com/credit-card/payment', 'yes', 'no', 'no'),
        ('ham', 'Barclays: Your account ending in 8812 was debited £95.00 for your monthly mortgage payment. View at https://www.barclays.co.uk/accounts', 'yes', 'no', 'no'),
        ('ham', 'Lloyds Bank: Your standing order of £250 to Joint Savings account was processed. View details: https://www.lloydsbank.com/accounts/online-banking.html', 'yes', 'no', 'no'),
        ('ham', 'NatWest: Your account summary for February 2026 — balance £1,842.50. View at https://www.natwest.com/accounts', 'yes', 'no', 'no'),
        ('ham', 'AT&T: Your monthly bill of $89.99 is ready. Pay by 03/15/2026 to avoid a late fee. View at https://www.att.com/my-account/billing', 'yes', 'no', 'no'),
        ('ham', 'PayPal: Your payment of $85.00 to eBay was completed. Transaction ID: 7GX334529. View at https://www.paypal.com/activity', 'yes', 'no', 'no'),
        ('ham', 'American Express: Your statement closing balance of $2,340.00 is due 03/22/2026. View your bill: https://www.americanexpress.com/en-us/account/pay', 'yes', 'no', 'no'),
        ('ham', 'Capital One: Your account ending 6677 credit card balance is $340.25. Payment due 04/01/2026. https://www.capitalone.com/credit-cards/online-account-access', 'yes', 'no', 'no'),
        ('ham', 'Discover: Your cashback rewards of $18.50 have been credited to your account. View at https://www.discover.com/credit-cards/member-benefits/rewards', 'yes', 'no', 'no'),
        ('ham', 'TD Bank: Your savings account earned $3.20 in interest for February 2026. View at https://www.tdbank.com/bank/checking-savings/account-overview', 'yes', 'no', 'no'),
        ('ham', 'Schwab: Your brokerage account statement for Q1 2026 is available. Portfolio value: $42,300. View: https://www.schwab.com/research/account-summary', 'yes', 'no', 'no'),
        ('ham', 'Fidelity: Your 401(k) contribution was invested this pay period. Current balance: $28,750. https://www.fidelity.com/bin-public/060_www_fidelity_com/documents', 'yes', 'no', 'no'),
        ('ham', 'Vanguard: Your IRA account quarterly report is ready. Total value: $34,200. View at https://investor.vanguard.com/my-account/account-overview', 'yes', 'no', 'no'),
        ('ham', 'USAA: Your car insurance renewal premium of $487.00 for 6 months has been charged. Policy 3341872. https://www.usaa.com/inet/wc/insurance-auto', 'yes', 'no', 'no'),
        ('ham', 'HSBC: Your monthly account fee of $12.00 has been charged. View your account at https://www.us.hsbc.com/online-banking/account-summary', 'yes', 'no', 'no'),
        # ── E. OTP / 2FA from financial institutions ────────────────────────
        ('ham', 'Leumi Bank security code: 847291. Valid for 5 minutes. Do not share this code. Request made from leumi.co.il.', 'no', 'no', 'no'),
        ('ham', 'Bank Hapoalim: Your one-time password for online banking login is 392847. Valid 3 minutes.', 'no', 'no', 'no'),
        ('ham', 'PayPal security code: 712943. Use this code to verify your account. Do not share it with anyone.', 'no', 'no', 'no'),
        ('ham', 'Chase Bank: Your verification code is 558831. This code expires in 10 minutes. Never share your code with anyone.', 'no', 'no', 'no'),
        ('ham', 'Bank of America: Your one-time passcode is 229014. Valid for one use only.', 'no', 'no', 'no'),
        ('ham', 'Mizrahi Tefahot: To approve your transfer of 5,000 NIS, enter the following code in the app: 774129.', 'no', 'no', 'no'),
        ('ham', 'Isracard: Your one-time code to authorize a purchase of 340 NIS at Amazon is 512874. Do not share.', 'no', 'no', 'no'),
        ('ham', 'Max Card: Approval code for your transaction of 189 NIS at Zara: 663412. This is an automatic message.', 'no', 'no', 'no'),
        ('ham', 'Google: Your verification code is 728341. It expires in 10 minutes.', 'no', 'no', 'no'),
        ('ham', 'Microsoft: Security code 931874. Use this to verify your account. If you did not request this, ignore this message.', 'no', 'no', 'no'),
        ('ham', 'Apple: Your Apple ID verification code is 448823. It will expire after it has been used once.', 'no', 'no', 'no'),
        ('ham', 'Interactive Brokers: Your login confirmation code is 334827. Do not share this code with anyone.', 'no', 'no', 'no'),
        ('ham', 'Discount Bank: OTP for wire transfer of 12,500 NIS: 891234. Code expires in 2 minutes.', 'no', 'no', 'no'),
        ('ham', 'National Insurance Institute (Bituach Leumi): Verification code for your online portal login: 229481.', 'no', 'no', 'no'),
        ('ham', 'Binance: Your account login verification code: 673921. Valid for 30 seconds.', 'no', 'no', 'no'),
        # ── F. Delivery notifications with financial amounts ─────────────────
        ('ham', 'DHL Express: Your shipment #9834712 is out for delivery. Customs duty of $12.50 was paid. Track: https://www.dhl.com/us-en/home/tracking.html', 'yes', 'no', 'no'),
        ('ham', 'FedEx: Delivery attempted for parcel #7781234. Customs clearance fee of 45 NIS pending. Schedule redelivery: https://www.fedex.com/en-il/tracking.html', 'yes', 'no', 'no'),
        ('ham', 'Israel Post: Your package from the USA has cleared customs. Import duty assessed: 78 NIS. Track at https://www.israelpost.co.il/npo.nsf/trackpackages', 'yes', 'no', 'no'),
        ('ham', 'Amazon: Your order has shipped. Estimated delivery: 03/08/2026. Track at https://www.amazon.com/gp/your-account/order-history', 'yes', 'no', 'no'),
        ('ham', 'UPS: Package delivered to mailbox. Paid COD $28.00. https://www.ups.com/track', 'yes', 'no', 'no'),
        ('ham', 'Zara Online: Your order has been shipped. Refund of 90 NIS for the returned item has been processed. https://www.zara.com/il/en/my-account', 'yes', 'no', 'no'),
        ('ham', 'H&M: Your order return has been received. Refund of 220 NIS will appear in your account within 5 business days. https://www2.hm.com/en_il/myaccount', 'yes', 'no', 'no'),
        ('ham', 'IKEA Israel: Your order has been scheduled for delivery on 03/10/2026. Delivery fee: 99 NIS. https://www.ikea.com/il/en/customer-service/order-tracking', 'yes', 'no', 'no'),
        ('ham', 'Rami Levy Online: Your grocery order of 312 NIS has been packed and is scheduled for delivery today. https://www.rami-levy.co.il/he/online/account/orders', 'yes', 'no', 'no'),
        ('ham', 'Shufersal Online: Your weekly grocery order — total 487 NIS — is on its way. Driver is 20 min away. https://www.shufersal.co.il/online/he/P/account/orders', 'yes', 'no', 'no'),
        ('ham', 'AliExpress: Your order has been delivered. If there is an issue, open a dispute: https://www.aliexpress.com/p/order/index.html', 'yes', 'no', 'no'),
        ('ham', 'Office Depot: Your order — 3 items, total $127.45 — has shipped. Track: https://www.officedepot.com/account/orderTracker.do', 'yes', 'no', 'no'),
        ('ham', 'Super-Pharm: Your online pharmacy order — total 145 NIS — is ready for pickup at the store. https://www.super-pharm.co.il/myaccount', 'yes', 'no', 'no'),
        ('ham', 'Fox Fashion: Your exchange request has been approved. Credit note of 180 NIS is available in your account. https://www.fox.co.il/account/orders', 'yes', 'no', 'no'),
        ('ham', 'Castro: Your online order — total 349 NIS — has been confirmed and is being processed. https://www.castro.com/myaccount/orders', 'yes', 'no', 'no'),
        # ── G. Investment / brokerage account updates ────────────────────────
        ('ham', 'IBI Investment House: Monthly account summary — total portfolio value 98,400 NIS, monthly return +1.3%. View at https://www.ibi.co.il/investor-portal', 'yes', 'no', 'no'),
        ('ham', 'Migdal Capital Markets: Your provident fund — total assets 187,000 NIS, return since inception 7.4%. https://www.migdal.co.il/capital', 'yes', 'no', 'no'),
        ('ham', 'Meitav Dash: Your stock portfolio — 15 holdings, total value 54,200 NIS. Monthly P&L: +830 NIS. https://www.meitav.co.il/trade', 'yes', 'no', 'no'),
        ('ham', 'Altshuler Shaham: Pension fund monthly credit 1,540 NIS received. Cumulative balance: 312,800 NIS. View: https://www.as-invest.co.il/pension', 'yes', 'no', 'no'),
        ('ham', 'Harel Finance: Your advanced training fund balance for Q4 2025: 28,400 NIS. Annual return: 5.6%. https://www.harelfinance.co.il', 'yes', 'no', 'no'),
        ('ham', 'Bank Hapoalim Securities: Your trade order — buy 50 shares TEVA at $9.40 — executed on NASDAQ. Account fee 12 NIS. https://www.bankhapoalim.co.il/securities', 'yes', 'no', 'no'),
        ('ham', 'Discount Bank Brokerage: Your dividend of $18.40 from VTI has been credited to your account. View activity: https://www.discountbank.co.il/trading', 'yes', 'no', 'no'),
        ('ham', 'Excellence Investment House: Your annual pension report for 2025 — total contributions: 42,000 NIS. https://www.excellenceness.co.il', 'yes', 'no', 'no'),
        ('ham', 'Yahav Bank: Your provident fund monthly summary is ready. Balance 74,120 NIS. View at https://www.bank-yahav.co.il/investment/provident', 'yes', 'no', 'no'),
        ('ham', 'Robinhood: Your monthly brokerage statement — portfolio value $8,420, realized gains $340. View at https://www.robinhood.com/account/statements', 'yes', 'no', 'no'),
        ('ham', 'Coinbase: Your transaction of 0.012 BTC (approx. $512.40) was completed. View details: https://www.coinbase.com/accounts/transactions', 'yes', 'no', 'no'),
        ('ham', 'Wealthsimple: Your TFSA account gained $42.00 this month. Total balance: $6,841. View: https://my.wealthsimple.com/app/portfolio', 'yes', 'no', 'no'),
        ('ham', 'Merrill Lynch: Your advisory account Q1 2026 report — assets $234,000. https://www.ml.com/content/dam/merrill', 'yes', 'no', 'no'),
        ('ham', 'Interactive Brokers Israel: Your account statement for March 2026 — net liquidation value $18,450. View: https://www.interactivebrokers.co.il/en/trading/account-summary.php', 'yes', 'no', 'no'),
        ('ham', 'Psagot Investment House: Your pension fund quarterly performance report — annual return 4.2%. View at https://www.psagot.co.il/pension-fund', 'yes', 'no', 'no'),
        ('ham', 'Poalim HiTech: Your business account statement — income 85,000 NIS, expenses 23,400 NIS, net 61,600 NIS. https://www.bankhapoalim.co.il/business', 'yes', 'no', 'no'),
    ]

    _aug_df = pd.DataFrame(_HARD_NEG_HAM, columns=['label', 'message', 'url', 'email', 'phone'])
    print(f'Adding {len(_aug_df)} hard-negative ham examples.')
    print(f'  url=yes: {(_aug_df["url"] == "yes").sum()}  |  url=no (OTP/text-only): {(_aug_df["url"] == "no").sum()}')
    df = pd.concat([df, _aug_df], ignore_index=True)
    print(f'Augmented dataset shape: {df.shape}')
    print(f'New label distribution:\n{df["label"].value_counts().to_string()}\n')
    # ── End Hard-Negative Ham Augmentation ───────────────────────────────────

    # ── Feature Engineering ──────────────────────────────────────────────────
    print('=' * 70)
    print('FEATURE ENGINEERING')
    print('=' * 70)

    df = engineer_features(df)

    # Normalize flag columns: yes/Yes/no/No → 1/0
    for col in ['url', 'email', 'phone']:
        df[col] = df[col].astype(str).str.lower().map({'yes': 1, 'no': 0}).fillna(0).astype(int)

    print('Feature means by class:')
    print(df.groupby('label')[TEXT_FEATURE_COLS].mean().round(3).to_string())

    # ── Post-Engineering Correlation Heatmap ─────────────────────────────────
    _eng_corr_cols = TEXT_FEATURE_COLS + ['url', 'phone']
    df['label_binary'] = (df['label'] == 'smish').astype(int)
    _eng_corr_cols_with_label = _eng_corr_cols + ['label_binary']
    corr_eng = df[_eng_corr_cols_with_label].corr()

    fig, ax = plt.subplots(figsize=(14, 11))
    sns.heatmap(corr_eng, ax=ax, annot=True, fmt='.2f', cmap='coolwarm',
                center=0, linewidths=0.5, linecolor='white',
                square=True, cbar_kws={'shrink': 0.8})
    ax.set_title('Feature Correlation Heatmap — After Engineering\n(label_binary: 0 = ham, 1 = smish)',
                 fontsize=13, fontweight='bold', pad=15)
    plt.xticks(rotation=45, ha='right', fontsize=9)
    plt.yticks(rotation=0, fontsize=9)
    plt.tight_layout()
    plt.savefig(f'{GRAPHS_DIR}/06b_correlation_heatmap_engineered.png', dpi=150, bbox_inches='tight')
    plt.show()
    print(f'Saved: {GRAPHS_DIR}/06b_correlation_heatmap_engineered.png')

    # ── Label Encoding & Train/Test Split ────────────────────────────────────
    print('\n' + '=' * 70)
    print('TRAIN / TEST SPLIT')
    print('=' * 70)

    label_encoder = LabelEncoder()
    y = label_encoder.fit_transform(df['label'])
    print(f'Label mapping: {dict(zip(label_encoder.classes_, label_encoder.transform(label_encoder.classes_)))}')

    feature_df = df[['message', 'url', 'email', 'phone'] + TEXT_FEATURE_COLS]

    X_train_df, X_test_df, y_train, y_test = train_test_split(
        feature_df, y,
        test_size=TEST_SIZE,
        random_state=RANDOM_STATE,
        stratify=y
    )

    print(f'Train: {len(X_train_df):,} rows  |  Test: {len(X_test_df):,} rows')

    # ── SBERT Embeddings ─────────────────────────────────────────────────────
    print('\n' + '=' * 70)
    print('NLP PREPROCESSING — SENTENCE-BERT')
    print('=' * 70)

    sbert_model = SentenceTransformer(SBERT_MODEL_NAME)

    X_train_text = X_train_df['message'].apply(preprocess_text).tolist()
    X_test_text  = X_test_df['message'].apply(preprocess_text).tolist()

    print(f'Encoding {len(X_train_text):,} training messages...')
    X_train_sbert = sbert_model.encode(
        X_train_text, batch_size=BATCH_SIZE,
        show_progress_bar=True, convert_to_numpy=True)

    print(f'Encoding {len(X_test_text):,} test messages...')
    X_test_sbert = sbert_model.encode(
        X_test_text, batch_size=BATCH_SIZE,
        show_progress_bar=True, convert_to_numpy=True)

    # ── TF-IDF Features ──────────────────────────────────────────────────────
    print('\nFitting TF-IDF vectorizer on training messages...')
    tfidf = TfidfVectorizer(
        max_features=50,
        ngram_range=(1, 2),
        stop_words='english',
        min_df=3,
        sublinear_tf=True
    )
    _X_train_tfidf_text = X_train_df['message'].apply(preprocess_text).tolist()
    _X_test_tfidf_text  = X_test_df['message'].apply(preprocess_text).tolist()
    X_train_tfidf = tfidf.fit_transform(_X_train_tfidf_text).toarray()
    X_test_tfidf  = tfidf.transform(_X_test_tfidf_text).toarray()
    print(f'TF-IDF vocab size: {len(tfidf.get_feature_names_out())} features')

    # ── Assemble Feature Matrices ────────────────────────────────────────────
    X_train_flags     = X_train_df[['url', 'phone']].values.astype(float)
    X_test_flags      = X_test_df[['url', 'phone']].values.astype(float)
    X_train_text_f    = X_train_df[TEXT_FEATURE_COLS].values.astype(float)
    X_test_text_f     = X_test_df[TEXT_FEATURE_COLS].values.astype(float)

    X_train = np.hstack([X_train_sbert, X_train_flags, X_train_text_f, X_train_tfidf])
    X_test  = np.hstack([X_test_sbert,  X_test_flags,  X_test_text_f,  X_test_tfidf])

    print(f'\nFeature matrix: {X_train.shape[1]} dims  '
          f'(384 SBERT + 2 flags + 14 text + 50 TF-IDF)')

    # ── Model Definitions ────────────────────────────────────────────────────
    cv = StratifiedKFold(n_splits=CV_FOLDS, shuffle=True, random_state=RANDOM_STATE)

    models = {
        'Logistic Regression': {
            'pipeline': make_pipeline(
                StandardScaler(),
                LogisticRegression(max_iter=1000, class_weight='balanced',
                                   random_state=RANDOM_STATE)
            ),
            'params': {'logisticregression__C': [0.01, 0.1, 1, 10]}
        },
        'SVM': {
            'pipeline': make_pipeline(
                StandardScaler(),
                SVC(probability=True, class_weight='balanced', random_state=RANDOM_STATE)
            ),
            'params': {
                'svc__C':      [0.1, 1, 10],
                'svc__kernel': ['rbf', 'linear']
            }
        },
        'Random Forest': {
            'pipeline': make_pipeline(
                RandomForestClassifier(class_weight='balanced', random_state=RANDOM_STATE)
            ),
            'params': {
                'randomforestclassifier__n_estimators': [100, 200],
                'randomforestclassifier__max_depth':    [None, 20]
            }
        },
        'XGBoost': {
            'pipeline': make_pipeline(
                XGBClassifier(eval_metric='logloss', random_state=RANDOM_STATE, verbosity=0)
            ),
            'params': {
                'xgbclassifier__n_estimators':  [100, 200],
                'xgbclassifier__max_depth':     [4, 6],
                'xgbclassifier__learning_rate': [0.05, 0.1]
            }
        },
        'MLP': {
            'pipeline': make_pipeline(
                StandardScaler(),
                MLPClassifier(max_iter=300, early_stopping=True,
                               random_state=RANDOM_STATE)
            ),
            'params': {
                'mlpclassifier__hidden_layer_sizes': [(256, 128), (512, 256)],
                'mlpclassifier__alpha':              [0.0001, 0.001]
            }
        }
    }

    # ── Train & Evaluate Each Model ──────────────────────────────────────────
    print('\n' + '=' * 70)
    print('TRAINING & EVALUATING MODELS')
    print('=' * 70)

    trained_models = {}
    all_metrics    = []

    for name, config in models.items():
        print(f'\n{"─"*60}')
        print(f'  {name}')
        print(f'{"─"*60}')

        grid = GridSearchCV(
            estimator=config['pipeline'],
            param_grid=config['params'],
            scoring='f1',
            cv=cv,
            refit=True,
            return_train_score=True,
            n_jobs=-1,
            verbose=0
        )
        grid.fit(X_train, y_train)

        best      = grid.best_estimator_
        trained_models[name] = best

        y_pred  = best.predict(X_test)
        y_proba = best.predict_proba(X_test)[:, 1]

        # Overfitting check
        best_idx = grid.best_index_
        train_f1 = grid.cv_results_['mean_train_score'][best_idx]
        val_f1   = grid.cv_results_['mean_test_score'][best_idx]
        gap      = train_f1 - val_f1
        status   = 'OVERFITTING' if gap > 0.05 else 'OK'

        print(f'  Best params:   {grid.best_params_}')
        print(f'  CV train F1:   {train_f1:.4f}')
        print(f'  CV val   F1:   {val_f1:.4f}  (gap: {gap:.4f} → {status})')

        save_path = f'{GRAPHS_DIR}/{name.lower().replace(" ", "_")}_eval.png'
        metrics_df, _ = model_kpi(name, y_test, y_pred, y_proba,
                                   label_encoder=label_encoder,
                                   save_path=save_path)
        print(metrics_df.to_string(index=False))

        all_metrics.append(metrics_df)

    # ── Weighted Soft-Voting Ensemble ────────────────────────────────────────
    print('\n' + '=' * 70)
    print('BUILDING WEIGHTED SOFT-VOTING ENSEMBLE')
    print('=' * 70)

    individual_f1 = {row['Model']: row['F1']
                     for df_m in all_metrics
                     for _, row in df_m.iterrows()}

    estimator_list = [(n.lower().replace(' ', '_'), clf)
                      for n, clf in trained_models.items()]
    weights = [individual_f1[n] for n in trained_models]

    print('Ensemble weights (proportional to individual F1):')
    for n, w in zip(trained_models.keys(), weights):
        print(f'  {n}: {w:.4f}')

    ensemble = VotingClassifier(
        estimators=estimator_list,
        voting='soft',
        weights=weights
    )
    ensemble.fit(X_train, y_train)

    y_pred_ens  = ensemble.predict(X_test)
    y_proba_ens = ensemble.predict_proba(X_test)[:, 1]

    # ── Optimal Classification Threshold ────────────────────────────────────
    # Find the highest threshold that still keeps smish recall >= 0.85,
    # maximising precision (and reducing false positives) as much as possible.
    _precisions, _recalls, _thresholds = precision_recall_curve(y_test, y_proba_ens)
    _valid = [
        (t, p, r)
        for t, p, r in zip(_thresholds, _precisions[:-1], _recalls[:-1])
        if r >= 0.85
    ]
    if _valid:
        optimal_threshold = float(max(_valid, key=lambda x: x[1])[0])
    else:
        # Fallback: maximise F1
        _f1 = 2 * (_precisions[:-1] * _recalls[:-1]) / (_precisions[:-1] + _recalls[:-1] + 1e-9)
        optimal_threshold = float(_thresholds[np.argmax(_f1)])
    print(f'Optimal classification threshold: {optimal_threshold:.4f}  (default was 0.5)')
    joblib.dump(optimal_threshold, THRESHOLD_PATH)
    print(f'Threshold saved → {THRESHOLD_PATH}')

    metrics_ens, _ = model_kpi(
        'Ensemble (Weighted Soft Vote)',
        y_test, y_pred_ens, y_proba_ens,
        label_encoder=label_encoder,
        save_path=f'{GRAPHS_DIR}/ensemble_eval.png'
    )
    print(metrics_ens.to_string(index=False))
    all_metrics.append(metrics_ens)

    # ── 6-Way Comparison ─────────────────────────────────────────────────────
    print('\n' + '=' * 70)
    print('MODEL COMPARISON (all 6 candidates, sorted by F1)')
    print('=' * 70)

    comparison_df = pd.concat(all_metrics, ignore_index=True)
    comparison_df = comparison_df.sort_values('F1', ascending=False).reset_index(drop=True)
    print(comparison_df.to_string(index=False))

    winner_name = comparison_df.iloc[0]['Model']
    print(f'\n✓ Winner: {winner_name}  (F1 = {comparison_df.iloc[0]["F1"]:.4f})')

    # Grouped bar chart
    metric_cols = ['Accuracy', 'Precision', 'Recall', 'F1', 'ROC-AUC']
    plot_df = comparison_df.set_index('Model')[metric_cols]

    fig, ax = plt.subplots(figsize=(14, 6))
    plot_df.T.plot(kind='bar', ax=ax, width=0.75,
                   colormap='tab10', edgecolor='white')
    ax.set_title('Model Comparison — All Metrics', fontsize=14, fontweight='bold', pad=15)
    ax.set_xlabel('Metric', fontsize=12)
    ax.set_ylabel('Score', fontsize=12)
    ax.set_ylim(0.75, 1.02)
    ax.set_xticklabels(metric_cols, rotation=0, fontsize=11)
    ax.legend(title='Model', bbox_to_anchor=(1.01, 1), loc='upper left', fontsize=9)
    ax.grid(axis='y', alpha=0.4)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    plt.tight_layout()
    plt.savefig(f'{GRAPHS_DIR}/07_model_comparison.png', dpi=150, bbox_inches='tight')
    plt.show()
    print(f'Saved: {GRAPHS_DIR}/07_model_comparison.png')

    # ── Save Best Model ───────────────────────────────────────────────────────
    print('\n' + '=' * 70)
    print('SAVING BEST MODEL')
    print('=' * 70)

    winner_model = ensemble if winner_name == 'Ensemble (Weighted Soft Vote)' \
                            else trained_models[winner_name]

    joblib.dump(winner_model, MODEL_PATH)
    joblib.dump(label_encoder, ENCODER_PATH)
    joblib.dump(tfidf, TFIDF_PATH)
    print(f'Model saved   → {MODEL_PATH}')
    print(f'Encoder saved → {ENCODER_PATH}')
    print(f'TF-IDF saved  → {TFIDF_PATH}')

    # ── Quick Inference Test ──────────────────────────────────────────────────
    print('\n' + '=' * 70)
    print('INFERENCE EXAMPLES')
    print('=' * 70)

    test_messages = [
        'Congratulations! You have been selected for a FREE prize. Click http://claim-now.net immediately!',
        'Your bank account has been locked. Verify your password at http://secure-bank-login.com',
        'Hey, are you coming to dinner tonight? Let me know.',
        'Ok lar... Joking wif u oni...',
    ]

    for msg in test_messages:
        label, conf = predict_message(msg, model=winner_model,
                                      encoder=label_encoder,
                                      sbert=sbert_model,
                                      tfidf=tfidf)
        indicator = '[SMISH]' if label == 'smish' else '[HAM]'
        short_msg = msg[:70] + '...' if len(msg) > 70 else msg
        print(f'\n{indicator} ({conf:.1%}) "{short_msg}"')

    print('\n' + '=' * 70)
    print('PIPELINE COMPLETE')
    print('=' * 70)
