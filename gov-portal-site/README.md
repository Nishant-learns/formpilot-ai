# 🏛️ Public Recruitment Portal Simulator (Demo Site)

A standalone public recruitment & examination practice portal simulator designed for testing **FormPilot** without touching real government infrastructure.

## 🚀 1-Click Deployment to Vercel

### Option 1: Via GitHub & Vercel Dashboard
1. Create a new GitHub repository (e.g. `gov-portal-demo`).
2. Push the files in this folder (`gov-portal-site`) to your new repository:
   ```bash
   cd gov-portal-site
   git init
   git add .
   git commit -m "Initial commit of Gov Portal Simulator"
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/gov-portal-demo.git
   git push -u origin main
   ```
3. Go to [vercel.com/new](https://vercel.com/new), select your repo, and click **Deploy**.
4. You will get a live public URL (e.g., `https://gov-portal-demo.vercel.app`)!

### Option 2: Via Vercel CLI (Instant)
```bash
cd gov-portal-site
npx vercel
```
Follow the interactive prompts to deploy directly from your terminal.

---

## 🎯 Testing with FormPilot
Once deployed, copy your live Vercel URL and paste it into FormPilot's **Official Portal or Exam Name** search bar!
FormPilot will automatically connect, observe the portal structure, fill from your candidate vault, and stop safely at OTP, CAPTCHA, and pre-payment checkpoints.
# gov-portal-demo
