#!/bin/bash
# Quick reference commands for email automation with improved deliverability

echo "📧 Email Automation - Quick Commands"
echo "===================================="
echo ""

echo "1️⃣  START SAFE CAMPAIGN (Recommended)"
echo "   python main.py"
echo ""

echo "2️⃣  START WITH API SERVER (for dashboard)"
echo "   python main.py --serve"
echo ""

echo "3️⃣  ANALYZE BOUNCE PATTERNS"
echo "   python bounce_analyzer.py"
echo ""

echo "4️⃣  ANALYZE LAST 14 DAYS"
echo "   python bounce_analyzer.py --days 14"
echo ""

echo "5️⃣  REMOVE HARD BOUNCES (skip in next campaign)"
echo "   python bounce_analyzer.py --cleanup"
echo ""

echo "6️⃣  MIGRATE DATABASE"
echo "   python main.py --migrate"
echo ""

echo "📊 SETTINGS IN .env (for tuning)"
echo "   • MAX_CONCURRENT_EMAILS=1 (increase to 2-3 only if needed)"
echo "   • DELAY_BETWEEN_EMAILS=3 (increase to 5+ if Gmail rejects)"
echo "   • SMTP_MAX_RETRIES=1 (only retry soft bounces)"
echo ""

echo "💡 WORKFLOW"
echo "   1. Import leads via frontend or CSV"
echo "   2. Run: python bounce_analyzer.py --cleanup"
echo "   3. Run: python main.py"
echo "   4. Wait 1 hour"
echo "   5. Run: python bounce_analyzer.py"
echo "   6. Review bounce patterns"
echo "   7. Adjust email template if bounce rate > 10%"
echo ""

echo "🔍 EXPECTED METRICS"
echo "   • Bounce rate: 5-15% (normal)"
echo "   • Spam rate: <5% (after improvements)"
echo "   • Hard bounces: Remove these"
echo "   • Soft bounces: Can retry"
echo ""
