// About page + legal documents (English). Plain text only — rendered with {{ }}, never v-html.
// Legal text must be reviewed by a Hong Kong solicitor before launch.
export default {
  updated: 'Last updated {date}',
  backHome: 'Back to home',
  contents: 'Contents',
  footer: {
    rights: '© {year} Grocer. Prices shown in HKD.',
  },

  about: {
    kicker: 'About Grocer',
    title: 'Compare prices. Let the agent do the shopping.',
    lead:
      'Grocer brings Hong Kong supermarket and pharmacy prices into one place, finds the cheapest store for every item, and lets an AI agent check out for you, inside spending rules you control.',
    cta: 'Compare prices',
    whatTitle: 'What Grocer does',
    whatText: 'One search instead of four shopping apps.',
    steps: [
      { title: 'Compare', text: 'We show the price of the same product at Watsons, HKTVmall, PARKnSHOP and Japan Home Centre, including delivery.' },
      { title: 'Protect', text: 'Spending rules are fixed in code, not decided by AI: HK$500 per order, approval up to HK$800, HK$2,000 a month.' },
      { title: 'Buy', text: 'The agent checks out at the cheapest store. Bigger orders wait for your approval for 10 minutes, then cancel.' },
    ],
    principlesTitle: 'Our principles',
    principles: [
      { title: 'Ranking cannot be bought', text: 'Stores cannot pay to appear higher. Prices are sorted by what you actually pay.' },
      { title: 'You stay in control', text: 'The agent can only spend inside your rules, at stores you allow. You can switch it off at any time.' },
      { title: 'Every step is recorded', text: 'Each agent action is written to a hash-chained log, so nothing can be changed afterwards without it showing.' },
    ],
    contactTitle: 'Contact us',
    contactEmail: 'hello@grocer.example',
  },

  terms: {
    title: 'Terms of Service',
    intro:
      'These terms apply when you use Grocer, including price comparison and the AI shopping agent that can buy products and pay for them on your behalf. Please read them together with our Privacy Policy and Return Policy.',
    sections: [
      {
        title: 'Who we are',
        body: [
          'Grocer ("we", "us") is a price-comparison and automated-checkout service for customers in the Hong Kong Special Administrative Region.',
          'We are not a supermarket or pharmacy. Each product is sold by the merchant shown at checkout (for example Watsons, HKTVmall, PARKnSHOP or Japan Home Centre). The contract of sale is between you and that merchant.',
        ],
      },
      {
        title: 'Your account',
        body: [
          'You must be 18 or over to create an account and use the shopping agent. A parent or guardian may set up the agent and approve purchases for a household.',
          'You are responsible for keeping your sign-in secure. Tell us at once if you think someone else has used your account.',
        ],
      },
      {
        title: 'The shopping agent and your authorisation',
        body: [
          'When you switch on the agent, you authorise us to search for products, prepare a cart and place orders and payments on your behalf, only within the spending rules shown in the app. These are currently:',
          {
            list: [
              'Orders up to HK$500 (including delivery) may be placed automatically.',
              'Orders over HK$500 and up to HK$800 need your approval in the app. If you do not approve within 10 minutes, the order is cancelled and you are not charged.',
              'Orders over HK$800, and orders that would take your spending this month over HK$2,000, are always blocked.',
              'The agent only buys from merchants on the approved list.',
            ],
          },
          'These limits are applied by fixed rules, not by the AI. You can change your limits within these maximums, or withdraw your authorisation at any time in the app; this stops future orders but does not cancel orders already accepted by a merchant.',
          'The AI decides only what to search for and how many to buy. If it misunderstands your request, our Return Policy explains how we put it right at our cost.',
        ],
      },
      {
        title: 'Prices and product information',
        body: [
          'Prices, stock and product details come from merchants and may change. We work to keep them accurate, but the price that applies is the total ("landed cost", including delivery) shown when the order is placed or approved.',
          'If a merchant charges you more than the landed cost you approved, we will refund the difference.',
        ],
      },
      {
        title: 'Payments',
        body: [
          'All amounts are in Hong Kong dollars (HKD). Payments are processed by licensed third-party payment service providers through card networks such as Mastercard and UnionPay.',
          'Your card is stored by the payment provider as a token. We do not store your full card number or security code.',
          'Grocer does not hold money, balances or stored value for you. Each order is charged directly to your chosen payment method.',
          'Every payment carries a unique reference so the same order cannot be charged twice. If a payment is declined, the order is not placed and we tell you in the app.',
          'Price comparison is free. If we ever charge a service fee, it will be shown before you approve an order.',
        ],
      },
      {
        title: 'Cancelling an order',
        body: [
          'You can cancel any order that is waiting for your approval. Once a merchant has accepted an order, the merchant’s own cancellation rules apply; contact us and we will help.',
        ],
      },
      {
        title: 'Acceptable use',
        body: [
          'Do not misuse Grocer: for example, do not try to get around spending rules, interfere with the service, scrape it at scale, or use it for unlawful purposes. We may suspend accounts that do.',
        ],
      },
      {
        title: 'Our responsibility to you',
        body: [
          'Nothing in these terms limits your rights under Hong Kong law, including the Sale of Goods Ordinance (Cap. 26), the Supply of Services (Implied Terms) Ordinance (Cap. 457), the Trade Descriptions Ordinance (Cap. 362) and the Control of Exemption Clauses Ordinance (Cap. 71).',
          'We are responsible for losses caused by our own failure to provide the service with reasonable care and skill, including errors made by the agent. We are not responsible for the quality of goods sold by merchants; that is the merchant’s responsibility, and we will help you claim from them.',
        ],
      },
      {
        title: 'Changes to these terms',
        body: [
          'We may update these terms. If a change affects your rights or the agent’s spending rules, we will tell you in the app before it takes effect.',
        ],
      },
      {
        title: 'Law and disputes',
        body: [
          'These terms are governed by the laws of the Hong Kong Special Administrative Region. Please contact us first so we can try to resolve any problem.',
          'You may also contact the Consumer Council, or bring a claim of up to HK$75,000 in the Small Claims Tribunal.',
          'These terms are available in English, Traditional Chinese and Simplified Chinese. If there is any inconsistency, the English version prevails.',
        ],
      },
      {
        title: 'Contact',
        body: ['Email: support@grocer.example'],
      },
    ],
  },

  returns: {
    title: 'Return Policy',
    intro:
      'Grocer compares prices and, when you ask it to, buys products for you from merchants. This policy explains how returns and refunds work, and what we do when our agent makes a mistake.',
    sections: [
      {
        title: 'Who handles what',
        body: [
          'Products are sold by the merchant shown on your order. Returns for faulty or damaged goods are handled by that merchant under its own policy and Hong Kong law.',
          'Mistakes made by the Grocer agent, and problems with payments taken through Grocer, are handled by us.',
        ],
      },
      {
        title: 'Faulty, damaged, wrong or missing items',
        body: [
          'Under the Sale of Goods Ordinance (Cap. 26), goods must be of merchantable quality, fit for their purpose and match their description. If an item is faulty, damaged, spoiled, expired or not what was described:',
          {
            list: [
              'Tell us or the merchant as soon as possible. For fresh and chilled food, please report within 24 hours of delivery.',
              'Keep the item, its packaging and your order confirmation, and take a photo if you can.',
              'We will contact the merchant on your behalf and keep you updated.',
            ],
          },
        ],
      },
      {
        title: 'Agent mistakes: we fix them',
        body: [
          'If the agent bought something you did not ask for, report it within 14 days of delivery. This includes:',
          {
            list: [
              'the wrong product or the wrong quantity;',
              'an order from a merchant that is not on your approved list;',
              'any order outside your spending rules, or one you refused or did not approve in time.',
            ],
          },
          'We will cancel or arrange the return and refund the full amount, including delivery, at no cost to you. Every agent step is recorded in your audit log, which we use to check what happened.',
        ],
      },
      {
        title: 'Changing your mind',
        body: [
          'Hong Kong law does not give a general right to return goods just because you changed your mind. Change-of-mind returns depend on each merchant’s own policy. You can always cancel an order before you approve it.',
        ],
      },
      {
        title: 'Items that usually cannot be returned',
        body: [
          'For hygiene and safety, merchants usually do not accept returns of opened or perishable items unless they are faulty. These include fresh food, opened personal-care products, medicines and opened baby formula.',
        ],
      },
      {
        title: 'Refunds',
        body: [
          'Refunds go back to the original payment method in HKD. We start a refund within 3 business days of approving it. Your bank or card issuer may take another 7 to 14 business days to show it.',
          'If a merchant charged more than the landed cost you approved, we refund the difference automatically.',
        ],
      },
      {
        title: 'Unauthorised or duplicate charges',
        body: [
          'If you see a charge you do not recognise, or the same order charged twice, contact us straight away. You can also contact your card issuer. We will investigate using the payment reference and audit log.',
        ],
      },
      {
        title: 'Still not resolved?',
        body: [
          'You may contact the Consumer Council, or bring a claim of up to HK$75,000 in the Small Claims Tribunal.',
          'Email: support@grocer.example',
        ],
      },
    ],
  },

  privacy: {
    title: 'Privacy Policy',
    intro:
      'This policy explains how Grocer collects, uses and protects your personal data, in line with the Personal Data (Privacy) Ordinance (Cap. 486) ("PDPO") and its six Data Protection Principles.',
    sections: [
      {
        title: 'Who we are',
        body: [
          'Grocer is the data user responsible for your personal data. You can reach our data protection officer at privacy@grocer.example.',
        ],
      },
      {
        title: 'What we collect',
        body: [
          {
            list: [
              'Account data: your name, email address and password. Passwords are stored only in hashed form.',
              'Delivery data: delivery address and phone number, shared with the merchant that fulfils your order.',
              'Shopping data: searches, cart, favourites, the instructions you give the agent, orders and approvals.',
              'Payment data: a payment token, card network and last four digits. Your full card number and security code are held only by our payment provider.',
              'Spending rules and audit log: your limits, and a record of each agent step and decision.',
              'Device data: language, theme and basic technical logs needed to keep the service secure.',
            ],
          },
          'Today, your cart, favourites, language and theme are stored only in your own browser.',
        ],
      },
      {
        title: 'Why we use it',
        body: [
          {
            list: [
              'To compare prices and show you the cheapest stores.',
              'To run the shopping agent, place orders with merchants and arrange delivery.',
              'To process payments, refunds and disputes, and prevent fraud.',
              'To apply your spending rules and keep the audit log.',
              'To provide customer support and meet our legal obligations.',
            ],
          },
          'We only use your data for these purposes or directly related ones, unless you give your consent. We will only send you direct marketing if you agree, as required by Part 6A of the PDPO, and you can opt out at any time.',
        ],
      },
      {
        title: 'How the AI agent uses your data',
        body: [
          'Your shopping instructions are processed by an AI model provider acting for us. We send only what is needed to understand the request; we do not send your payment details.',
          'Spending decisions are made by fixed rules, not by the AI. We do not allow your data to be used to train AI models without your consent.',
        ],
      },
      {
        title: 'Who we share it with',
        body: [
          {
            list: [
              'Merchants: what they need to fulfil your order (name, delivery address, phone, items).',
              'Payment providers and card networks: to take payments and refunds.',
              'Service providers such as cloud hosting and AI model providers, under contracts that require them to protect your data and use it only for us.',
              'Authorities, where we are required to by law.',
            ],
          },
          'We do not sell your personal data.',
        ],
      },
      {
        title: 'Data stored outside Hong Kong',
        body: [
          'Some of our service providers may store or process data outside Hong Kong. When they do, we use contracts and safeguards so that your data receives protection comparable to the PDPO.',
        ],
      },
      {
        title: 'How long we keep it',
        body: [
          'We keep personal data only as long as needed for the purposes above. Order and payment records are kept for 7 years, as required for business records under the Inland Revenue Ordinance (Cap. 112). Other account data is deleted within 90 days after you close your account.',
        ],
      },
      {
        title: 'How we protect it',
        body: [
          'We use encryption in transit, tokenised payments, access controls and a hash-chained audit log. If a data breach is likely to cause you harm, we will tell you promptly and notify the Privacy Commissioner for Personal Data where appropriate.',
        ],
      },
      {
        title: 'Your rights',
        body: [
          'You may ask for a copy of your personal data and ask us to correct it. We will reply within 40 days, as the PDPO requires. We may charge a fee for a copy, which will not be excessive.',
          'You may also complain to the Office of the Privacy Commissioner for Personal Data, Hong Kong.',
        ],
      },
      {
        title: 'Browser storage and cookies',
        body: [
          'We use your browser’s local storage to remember your cart, favourites, language and theme. We do not use third-party advertising cookies.',
        ],
      },
      {
        title: 'Changes and language',
        body: [
          'We will tell you in the app about important changes to this policy. This policy is available in English, Traditional Chinese and Simplified Chinese; if there is any inconsistency, the English version prevails.',
        ],
      },
    ],
  },
}
