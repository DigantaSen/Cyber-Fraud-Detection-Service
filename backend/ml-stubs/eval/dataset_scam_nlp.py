"""
Labeled evaluation dataset for the Scam NLP Classifier (T9/T11).
50+ examples across the 5 scam categories + a benign/UNKNOWN negative set,
covering English and Hindi complaint text per FR-11.1 (12 regional languages).

Each record:
  text            -> raw complaint text
  languageCode    -> BCP-47 code
  complaintType   -> ComplaintType enum value
  category        -> ground-truth category label (matches contract enum)
  is_scam         -> ground truth binary label (True = fraudulent/risky)
"""

DATASET = [
    # ---------------- IMPERSONATION_FRAUD ----------------
    ("This is CBI. Transfer 50000 immediately or FIR and arrest will happen.",
     "en", "CALL_FRAUD", "IMPERSONATION_FRAUD", True),
    ("RBI officer here, your account will be blocked in 1 hour, share your OTP now.",
     "en", "CALL_FRAUD", "IMPERSONATION_FRAUD", True),
    ("Income tax department calling, pay penalty now or face court case tomorrow.",
     "en", "CALL_FRAUD", "IMPERSONATION_FRAUD", True),
    ("Customs department has seized your parcel, pay fine of Rs 15000 immediately to avoid arrest.",
     "en", "CALL_FRAUD", "IMPERSONATION_FRAUD", True),
    ("मैं पुलिस अधिकारी बोल रहा हूं, तुरंत पैसे ट्रांसफर करो नहीं तो गिरफ्तार हो जाओगे।",
     "hi", "CALL_FRAUD", "IMPERSONATION_FRAUD", True),
    ("Your Aadhaar is linked to a money laundering case, CBI needs you to pay a security deposit today.",
     "en", "CYBER_CRIME", "IMPERSONATION_FRAUD", True),
    ("This is court notice, FIR has been filed, pay fine immediately or face arrest by police tonight.",
     "en", "CALL_FRAUD", "IMPERSONATION_FRAUD", True),
    ("Bank officer here, verification pending, share your PIN and card number immediately to avoid account freeze.",
     "en", "CALL_FRAUD", "IMPERSONATION_FRAUD", True),
    ("सीबीआई अधिकारी हूं, आपके खिलाफ केस दर्ज है, अभी जुर्माना भरो नहीं तो जेल जाना पड़ेगा।",
     "hi", "CALL_FRAUD", "IMPERSONATION_FRAUD", True),
    ("Cyber crime officer speaking, your number is used in a criminal case, transfer money right now to clear your name.",
     "en", "CYBER_CRIME", "IMPERSONATION_FRAUD", True),
    ("Customs officer says a parcel with illegal items is in my name, I must pay a fine right now or be arrested.",
     "en", "CALL_FRAUD", "IMPERSONATION_FRAUD", True),

    # ---------------- UPI_SCAM ----------------
    ("Someone sent a UPI collect request on PhonePe and asked me to approve it to receive a refund.",
     "en", "UPI_FRAUD", "UPI_SCAM", True),
    ("I received a Google Pay request for Rs 500 claiming it is a cashback, I need to accept to get money.",
     "en", "UPI_FRAUD", "UPI_SCAM", True),
    ("Unknown person asked me to scan a QR code on Paytm to receive payment for selling my old phone.",
     "en", "UPI_FRAUD", "UPI_SCAM", True),
    ("Caller said I would get a refund only if I approve the UPI collect request they sent.",
     "en", "UPI_FRAUD", "UPI_SCAM", True),
    ("यूपीआई पर एक कलेक्ट रिक्वेस्ट आई है, कहा जा रहा है कि पैसे पाने के लिए मंजूर करो।",
     "hi", "UPI_FRAUD", "UPI_SCAM", True),
    ("Someone claiming to be from PhonePe support asked me to share my UPI PIN to fix a failed transaction.",
     "en", "UPI_FRAUD", "UPI_SCAM", True),
    ("I got a fake job offer where I need to pay a registration fee via UPI GPay to confirm my selection.",
     "en", "UPI_FRAUD", "UPI_SCAM", True),
    ("Buyer on OLX asked me to accept a UPI collect request to receive payment for my item.",
     "en", "UPI_FRAUD", "UPI_SCAM", True),
    ("एक अनजान नंबर से यूपीआई कलेक्ट रिक्वेस्ट आई और तुरंत भुगतान स्वीकार करने को कहा गया।",
     "hi", "UPI_FRAUD", "UPI_SCAM", True),

    # ---------------- INVESTMENT_FRAUD ----------------
    ("A Telegram group promised guaranteed crypto trading profit and asked me to invest more money.",
     "en", "CYBER_CRIME", "INVESTMENT_FRAUD", True),
    ("An app promised to double my money in 7 days if I invest in their trading scheme.",
     "en", "CYBER_CRIME", "INVESTMENT_FRAUD", True),
    ("Someone on WhatsApp is offering guaranteed returns of 30 percent monthly on stock trading, asked me to invest urgently.",
     "en", "CYBER_CRIME", "INVESTMENT_FRAUD", True),
    ("एक निवेश समूह ने गारंटीड मुनाफे का वादा किया और मुझसे और पैसे निवेश करने को कहा।",
     "hi", "CYBER_CRIME", "INVESTMENT_FRAUD", True),
    ("I was asked to deposit more crypto to unlock withdrawal from a trading platform that promised guaranteed returns.",
     "en", "CYBER_CRIME", "INVESTMENT_FRAUD", True),
    ("A financial advisor cold-called offering a mutual fund with guaranteed 25 percent annual return, urging me to invest immediately.",
     "en", "CYBER_CRIME", "INVESTMENT_FRAUD", True),
    ("Website promised doubling my investment in Forex trading within a week if I invest right now.",
     "en", "CYBER_CRIME", "INVESTMENT_FRAUD", True),
    ("निवेश ऐप ने कहा कि क्रिप्टो में मुनाफा गारंटीड है, तुरंत और पैसे लगाने को कहा।",
     "hi", "CYBER_CRIME", "INVESTMENT_FRAUD", True),

    # ---------------- LOTTERY_SCAM ----------------
    ("I received a message saying I won a lottery prize of 25 lakh and need to pay processing fee to claim it.",
     "en", "CYBER_CRIME", "LOTTERY_SCAM", True),
    ("Someone said I won a lucky draw gift and need to pay customs fee to receive the reward.",
     "en", "CYBER_CRIME", "LOTTERY_SCAM", True),
    ("एक मैसेज आया कि मैंने लॉटरी जीती है, इनाम पाने के लिए फीस भरनी होगी।",
     "hi", "CYBER_CRIME", "LOTTERY_SCAM", True),
    ("KBC lottery winner message asking me to pay tax to claim my prize money urgently.",
     "en", "CYBER_CRIME", "LOTTERY_SCAM", True),
    ("Email claims I won a free gift and cashback, just need to share bank details to receive it.",
     "en", "CYBER_CRIME", "LOTTERY_SCAM", True),
    ("WhatsApp message says I won a lottery worth 10 lakh rupees, pay a small registration fee to claim.",
     "en", "CYBER_CRIME", "LOTTERY_SCAM", True),
    ("मुझे इनाम जीतने का मैसेज मिला, गिफ्ट पाने के लिए पहले पैसे भेजने को कहा गया।",
     "hi", "CYBER_CRIME", "LOTTERY_SCAM", True),

    # ---------------- ROMANCE_SCAM ----------------
    ("An online friend I met on a dating app professed love within days and then asked for emergency financial help.",
     "en", "CYBER_CRIME", "ROMANCE_SCAM", True),
    ("Someone I matched with on a dating app claims to be stuck abroad and needs money for emergency medical help.",
     "en", "CYBER_CRIME", "ROMANCE_SCAM", True),
    ("मेरी दोस्ती एक ऑनलाइन व्यक्ति से हुई, उसने शादी का वादा किया और अब पैसे मांग रहा है।",
     "hi", "CYBER_CRIME", "ROMANCE_SCAM", True),
    ("My online partner professed love quickly and is now asking for money to book a flight to visit me.",
     "en", "CYBER_CRIME", "ROMANCE_SCAM", True),
    ("A person I met on Instagram claims to love me and wants gift cards for an emergency situation.",
     "en", "CYBER_CRIME", "ROMANCE_SCAM", True),
    ("ऑनलाइन डेटिंग ऐप पर मिले व्यक्ति ने शादी का वादा किया और अब इमरजेंसी बताकर पैसे मांग रहा है।",
     "hi", "CYBER_CRIME", "ROMANCE_SCAM", True),

    # ---------------- BENIGN / UNKNOWN (negative class) ----------------
    ("I want to know the status of my bank account statement request.",
     "en", "OTHER", "UNKNOWN", False),
    ("Please share the timing of the nearest police station for a lost documents complaint.",
     "en", "OTHER", "UNKNOWN", False),
    ("I would like to update my address in my bank KYC records.",
     "en", "OTHER", "UNKNOWN", False),
    ("Can you tell me how to reset my mobile banking app password through the official app?",
     "en", "OTHER", "UNKNOWN", False),
    ("I want information about opening a fixed deposit account at my local bank branch.",
     "en", "OTHER", "UNKNOWN", False),
    ("How do I file a complaint about a delayed courier delivery from an online store?",
     "en", "OTHER", "UNKNOWN", False),
    ("I need help checking my credit score through an official website.",
     "en", "OTHER", "UNKNOWN", False),
    ("What are the working hours of the passport office this week?",
     "en", "OTHER", "UNKNOWN", False),
    ("मुझे अपने बैंक खाते का स्टेटमेंट चाहिए, कृपया प्रक्रिया बताएं।",
     "hi", "OTHER", "UNKNOWN", False),
    ("I want to know how to link my PAN card with my bank account.",
     "en", "OTHER", "UNKNOWN", False),
]

assert len(DATASET) >= 50, f"expected >=50 examples, got {len(DATASET)}"
