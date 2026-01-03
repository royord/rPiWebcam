<?php
// config.php - Enhanced with email whitelist
define('EMAIL_HOST', 'imap.gmail.com');
define('EMAIL_PORT', 993);
define('EMAIL_USERNAME', 'your-email@gmail.com');
define('EMAIL_PASSWORD', 'your-app-password');
define('EMAIL_ENCRYPTION', 'ssl');

// Whitelist of allowed sender email addresses
define('ALLOWED_SENDERS', [
    'trusted@example.com',
    'admin@yourdomain.com',
    'updates@partner.com'
]);

// Additional security settings
define('CHECK_SPF', true);           // Verify SPF records
define('CHECK_DKIM', true);          // Verify DKIM signatures
define('REQUIRE_AUTHENTICATION', true); // Require authenticated sender
define('LOG_REJECTED_EMAILS', true); // Log rejected attempts