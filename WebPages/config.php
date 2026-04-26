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

// Whitelist of domains allowed in email body links
define(
    'ALLOWED_LINK_DOMAINS', [
    'forecast.weather.gov',
    'waterdata.usgs.gov',
    'www.cnrfc.noaa.gov',
    'cdec.water.ca.gov'
]);

// Blog settings
define('BLOG_DB_FILE', __DIR__ . '/blog_posts.json');
define('BLOG_BASE_URL', 'https://yourdomain.com/blog.php');
define('BLOG_EMAIL_FROM', 'no-reply@yourdomain.com');
define('BLOG_EMAIL_CHECK_TOKEN', 'change-this-email-check-token');
define('BLOG_DELETE_TOKEN_SECRET', 'change-this-delete-token-secret');
define('BLOG_EMAIL_CHECK_INTERVAL_SECONDS', 900);

// Additional security settings
define('CHECK_SPF', true);           // Verify SPF records
define('CHECK_DKIM', true);          // Verify DKIM signatures
define('REQUIRE_AUTHENTICATION', true); // Require authenticated sender
define('LOG_REJECTED_EMAILS', true); // Log rejected attempts