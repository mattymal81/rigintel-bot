# RigIntel Bot — GitHub Actions Setup

## Folder structure
```
rigintel-bot/
├── .github/
│   └── workflows/
│       └── weekly_sweep.yml   ← tells GitHub when and how to run
├── rig_intel_emailer.py       ← the main bot script
└── README.md                  ← this file
```

## One-time setup steps

### 1. Create a free GitHub account
Go to github.com and sign up if you don't have one.

### 2. Create a new repository
- Click the + icon (top right) → New repository
- Name it: rigintel-bot
- Set to Private
- Click Create repository

### 3. Upload your files
- Click "uploading an existing file" on the repo page
- Drag in: rig_intel_emailer.py and the .github folder
- Click Commit changes

### 4. Add your secret keys (no one can see these but you)
- Go to your repo → Settings → Secrets and variables → Actions
- Click "New repository secret" and add each one:

  Name: ANTHROPIC_API_KEY
  Value: sk-ant-your-key-here

  Name: SENDGRID_API_KEY
  Value: SG.your-key-here

  Name: EMAIL_FROM
  Value: rigintel@yourcompany.com

  Name: EMAIL_TO
  Value: salesperson@yourcompany.com

### 5. Test it manually
- Go to Actions tab in your repo
- Click "RigIntel Weekly Email" in the left sidebar
- Click "Run workflow" → Run workflow
- Watch it run — green checkmark means the email was sent

After that it fires automatically every Tuesday at 6:00 AM CDT.
