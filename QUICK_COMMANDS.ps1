# Quick reference commands for email automation with improved deliverability
# For Windows PowerShell

Write-Host "📧 Email Automation - Quick Commands (Windows)" -ForegroundColor Cyan
Write-Host "===========================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "1️⃣ START SAFE CAMPAIGN (Recommended)" -ForegroundColor Yellow
Write-Host "   python main.py" -ForegroundColor White
Write-Host ""

Write-Host "2️⃣ START WITH API SERVER (for dashboard)" -ForegroundColor Yellow
Write-Host "   python main.py --serve" -ForegroundColor White
Write-Host ""

Write-Host "3️⃣ ANALYZE BOUNCE PATTERNS" -ForegroundColor Yellow
Write-Host "   python bounce_analyzer.py" -ForegroundColor White
Write-Host ""

Write-Host "4️⃣ ANALYZE LAST 14 DAYS" -ForegroundColor Yellow
Write-Host "   python bounce_analyzer.py --days 14" -ForegroundColor White
Write-Host ""

Write-Host "5️⃣ REMOVE HARD BOUNCES (skip in next campaign)" -ForegroundColor Yellow
Write-Host "   python bounce_analyzer.py --cleanup" -ForegroundColor White
Write-Host ""

Write-Host "6️⃣ MIGRATE DATABASE" -ForegroundColor Yellow
Write-Host "   python main.py --migrate" -ForegroundColor White
Write-Host ""

Write-Host "7️⃣ VIEW API DOCS (after --serve)" -ForegroundColor Yellow
Write-Host "   http://localhost:8000/docs" -ForegroundColor Green
Write-Host ""

Write-Host "📊 SETTINGS IN .env (for tuning)" -ForegroundColor Cyan
Write-Host "   • MAX_CONCURRENT_EMAILS=1 (increase to 2-3 only if needed)" -ForegroundColor White
Write-Host "   • DELAY_BETWEEN_EMAILS=3 (increase to 5+ if Gmail rejects)" -ForegroundColor White
Write-Host "   • SMTP_MAX_RETRIES=1 (only retry soft bounces)" -ForegroundColor White
Write-Host ""

Write-Host "💡 RECOMMENDED WORKFLOW" -ForegroundColor Cyan
Write-Host "   1. Import leads via frontend (http://localhost:8000/frontend)" -ForegroundColor White
Write-Host "   2. Run: python bounce_analyzer.py --cleanup" -ForegroundColor White
Write-Host "   3. Run: python main.py" -ForegroundColor White
Write-Host "   4. Wait 1 hour" -ForegroundColor White
Write-Host "   5. Run: python bounce_analyzer.py" -ForegroundColor White
Write-Host "   6. Review bounce patterns from output" -ForegroundColor White
Write-Host "   7. Adjust if bounce rate > 10%" -ForegroundColor White
Write-Host ""

Write-Host "🔍 EXPECTED METRICS (Cold Email)" -ForegroundColor Cyan
Write-Host "   • Bounce rate: 5-15% (normal for cold outreach)" -ForegroundColor White
Write-Host "   • Spam rate: <5% (goal with improvements)" -ForegroundColor White
Write-Host "   • Reply rate: 2-8% (indicator of good list quality)" -ForegroundColor White
Write-Host ""

Write-Host "⚡ TROUBLESHOOTING" -ForegroundColor Cyan
Write-Host "   Bounce rate > 20%? → Email list quality issue" -ForegroundColor Red
Write-Host "   Spam rate > 10%?  → Email template is too salesy" -ForegroundColor Red
Write-Host "   Gmail rejects?     → Increase DELAY_BETWEEN_EMAILS to 5+" -ForegroundColor Red
Write-Host ""

Write-Host "📚 FULL DOCUMENTATION" -ForegroundColor Green
Write-Host "   See: DELIVERABILITY_IMPROVEMENTS.md" -ForegroundColor Cyan
