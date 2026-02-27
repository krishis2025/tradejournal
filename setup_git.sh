#!/bin/bash
# ═══════════════════════════════════════════════════════════════
#  Trade Journal — Git Setup & Push Script
#  Run this ONCE to initialize the repo and push to GitHub.
# ═══════════════════════════════════════════════════════════════

set -e

echo ""
echo "═══════════════════════════════════════════════════"
echo "  Trade Journal — Git Setup"
echo "═══════════════════════════════════════════════════"
echo ""

# ── Step 1: Check git is installed ──
if ! command -v git &> /dev/null; then
    echo "❌ git is not installed."
    echo "   Install it from: https://git-scm.com/downloads"
    exit 1
fi

# ── Step 2: Initialize repo if needed ──
if [ ! -d ".git" ]; then
    echo "📦 Initializing git repository..."
    git init
    git branch -M main
    echo "   ✓ Git initialized on 'main' branch"
else
    echo "✓ Git repo already exists"
fi

# ── Step 3: Configure git user if not set ──
if [ -z "$(git config user.email)" ]; then
    echo ""
    echo "⚙  Git user not configured. Setting defaults..."
    echo "   (You can change these later with: git config user.name / user.email)"
    read -p "   Your name: " GIT_NAME
    read -p "   Your email: " GIT_EMAIL
    git config user.name "$GIT_NAME"
    git config user.email "$GIT_EMAIL"
fi

# ── Step 4: Stage all files ──
echo ""
echo "📁 Staging files..."
git add -A
echo "   ✓ All files staged"

# ── Step 5: Show what will be committed ──
echo ""
echo "   Files to commit:"
git diff --cached --stat | head -20
echo ""

# ── Step 6: Create initial commit ──
VERSION=$(cat VERSION 2>/dev/null || echo "1.0.0")
echo "💾 Creating commit (v${VERSION})..."
git commit -m "v${VERSION} — Trade Journal initial release

Features:
- CSV/Excel import with FIFO trade reconstruction
- Live Trade Ticket UI (one-click exits, trailing stops, partials)
- 7 customizable tag groups
- Analytics (P&L charts, tag performance, time-of-day)
- Portfolio management
- 9 themes (Mint, Amber, Cyan, Arctic, Crimson, Purple, Mono, Paper, Soft Dark)
- DB export/import backup system
"
echo "   ✓ Committed"

# ── Step 7: Tag the release ──
git tag -a "v${VERSION}" -m "v${VERSION} — Initial release"
echo "   ✓ Tagged as v${VERSION}"

# ── Step 8: Prompt for GitHub remote ──
echo ""
echo "═══════════════════════════════════════════════════"
echo "  Ready to push!"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  Next steps:"
echo ""
echo "  1. Create a NEW repo on GitHub:"
echo "     https://github.com/new"
echo "     Name it: tradejournal (or whatever you prefer)"
echo "     Do NOT initialize with README (we already have one)"
echo ""
echo "  2. Then run these commands:"
echo ""
echo "     git remote add origin https://github.com/YOUR_USERNAME/tradejournal.git"
echo "     git push -u origin main"
echo "     git push --tags"
echo ""
echo "  For SSH (if you have SSH keys set up):"
echo "     git remote add origin git@github.com:YOUR_USERNAME/tradejournal.git"
echo "     git push -u origin main"
echo "     git push --tags"
echo ""

# ── Optional: Auto-add remote if user provides URL ──
read -p "  Paste your GitHub repo URL (or press Enter to skip): " REMOTE_URL
if [ -n "$REMOTE_URL" ]; then
    git remote remove origin 2>/dev/null || true
    git remote add origin "$REMOTE_URL"
    echo ""
    echo "🚀 Pushing to GitHub..."
    git push -u origin main
    git push --tags
    echo ""
    echo "   ✓ Pushed to $REMOTE_URL"
    echo "   ✓ Tagged release v${VERSION}"
fi

echo ""
echo "═══════════════════════════════════════════════════"
echo "  Done! Your Trade Journal repo is ready."
echo "═══════════════════════════════════════════════════"
echo ""
