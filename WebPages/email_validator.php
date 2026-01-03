<?php
// email_validator.php - Anti-spoofing validation
class EmailValidator {
    private $allowedSenders;
    private $logFile = 'rejected_emails.log';

    public function __construct($allowedSenders = []) {
        $this->allowedSenders = array_map('strtolower', $allowedSenders);
    }

    /**
     * Validate email sender with anti-spoofing checks
     */
    public function validateSender($emailId, $inbox) {
        $header = imap_headerinfo($inbox, $emailId);
        $fullHeader = imap_fetchheader($inbox, $emailId);

        // Extract all relevant email addresses
        $fromAddress = $this->extractEmail($header->fromaddress);
        $returnPath = $this->extractReturnPath($fullHeader);
        $replyTo = isset($header->reply_toaddress) ? $this->extractEmail($header->reply_toaddress) : null;

        // Validation result
        $result = [
            'valid' => false,
            'from' => $fromAddress,
            'return_path' => $returnPath,
            'reply_to' => $replyTo,
            'reasons' => [],
            'spf_pass' => false,
            'dkim_pass' => false,
            'authenticated' => false
        ];

        // 1. Check if sender is in whitelist
        if (!$this->isWhitelisted($fromAddress)) {
            $result['reasons'][] = "Sender not in whitelist: {$fromAddress}";
            $this->logRejection($emailId, $fromAddress, 'Not whitelisted');
            return $result;
        }

        // 2. Verify Return-Path matches From address
        if ($returnPath && strtolower($returnPath) !== strtolower($fromAddress)) {
            $result['reasons'][] = "Return-Path mismatch: From={$fromAddress}, Return-Path={$returnPath}";
            $this->logRejection($emailId, $fromAddress, 'Return-Path mismatch');
            return $result;
        }

        // 3. Check for authentication headers
        if (REQUIRE_AUTHENTICATION) {
            $result['authenticated'] = $this->checkAuthentication($fullHeader);
            if (!$result['authenticated']) {
                $result['reasons'][] = "No authentication found";
                $this->logRejection($emailId, $fromAddress, 'Not authenticated');
                return $result;
            }
        }

        // 4. Verify SPF (Sender Policy Framework)
        if (CHECK_SPF) {
            $result['spf_pass'] = $this->checkSPF($fullHeader);
            if (!$result['spf_pass']) {
                $result['reasons'][] = "SPF check failed";
                $this->logRejection($emailId, $fromAddress, 'SPF failed');
                return $result;
            }
        }

        // 5. Verify DKIM (DomainKeys Identified Mail)
        if (CHECK_DKIM) {
            $result['dkim_pass'] = $this->checkDKIM($fullHeader);
            if (!$result['dkim_pass']) {
                $result['reasons'][] = "DKIM check failed";
                $this->logRejection($emailId, $fromAddress, 'DKIM failed');
                return $result;
            }
        }

        // 6. Check for suspicious headers
        if ($this->hasSuspiciousHeaders($fullHeader)) {
            $result['reasons'][] = "Suspicious headers detected";
            $this->logRejection($emailId, $fromAddress, 'Suspicious headers');
            return $result;
        }

        // All checks passed
        $result['valid'] = true;
        return $result;
    }

    /**
     * Extract clean email address
     */
    private function extractEmail($emailString) {
        // Handle "Name <email@domain.com>" format
        if (preg_match('/<([^>]+)>/', $emailString, $matches)) {
            return strtolower(trim($matches));
        }

        // Clean and validate
        $email = filter_var(trim($emailString), FILTER_SANITIZE_EMAIL);
        return strtolower($email);
    }

    /**
     * Extract Return-Path from headers
     */
    private function extractReturnPath($headers) {
        if (preg_match('/Return-Path:\s*<?([^>\r\n]+)>?/i', $headers, $matches)) {
            return strtolower(trim($matches));
        }
        return null;
    }

    /**
     * Check if email is in whitelist
     */
    private function isWhitelisted($email) {
        $email = strtolower(trim($email));

        foreach ($this->allowedSenders as $allowed) {
            // Exact match
            if ($email === $allowed) {
                return true;
            }

            // Wildcard domain match (e.g., *@example.com)
            if (strpos($allowed, '*@') === 0) {
                $domain = substr($allowed, 2);
                if (preg_match('/@' . preg_quote($domain, '/') . '$/i', $email)) {
                    return true;
                }
            }
        }

        return false;
    }

    /**
     * Check authentication headers (DMARC, SPF, DKIM results)
     */
    private function checkAuthentication($headers) {
        // Check for Authentication-Results header
        if (preg_match('/Authentication-Results:.*?spf=pass/i', $headers)) {
            return true;
        }

        if (preg_match('/Authentication-Results:.*?dkim=pass/i', $headers)) {
            return true;
        }

        // Check for Received-SPF header
        if (preg_match('/Received-SPF:\s*pass/i', $headers)) {
            return true;
        }

        // Check for DKIM-Signature header
        if (preg_match('/DKIM-Signature:/i', $headers)) {
            return true;
        }

        return false;
    }

    /**
     * Verify SPF record
     */
    private function checkSPF($headers) {
        // Check Received-SPF header
        if (preg_match('/Received-SPF:\s*(pass|softfail)/i', $headers, $matches)) {
            return strtolower($matches) === 'pass';
        }

        // Check Authentication-Results for SPF
        if (preg_match('/Authentication-Results:.*?spf=(pass|fail|softfail|neutral)/i', $headers, $matches)) {
            return strtolower($matches) === 'pass';
        }

        // If no SPF header found, assume pass (some servers don't add this)
        return true;
    }

    /**
     * Verify DKIM signature
     */
    private function checkDKIM($headers) {
        // Check for DKIM-Signature header
        if (!preg_match('/DKIM-Signature:/i', $headers)) {
            // No DKIM signature present
            return false;
        }

        // Check Authentication-Results for DKIM
        if (preg_match('/Authentication-Results:.*?dkim=(pass|fail|neutral)/i', $headers, $matches)) {
            return strtolower($matches) === 'pass';
        }

        // If DKIM signature exists but no validation result, assume pass
        return true;
    }

    /**
     * Check for suspicious headers that indicate spoofing
     */
    private function hasSuspiciousHeaders($headers) {
        $suspicious = [
            // Multiple From headers
            '/^From:.*?^From:/ims',

            // Mismatched Message-ID domain
            '/Message-ID:.*?@(?!(' . implode('|', array_map(function($email) {
                return preg_quote(substr(strrchr($email, '@'), 1), '/');
            }, $this->allowedSenders)) . '))/i',

            // X-Mailer indicating known spoofing tools
            '/X-Mailer:.*(PHPMailer|SwiftMailer).*\bv?[0-9]\.[0-9]/i',

            // Suspicious Received headers (too few or malformed)
            // Most legitimate emails have at least 2-3 Received headers
        ];

        foreach ($suspicious as $pattern) {
            if (preg_match($pattern, $headers)) {
                return true;
            }
        }

        // Check number of Received headers (should be at least 2 for legitimate email)
        $receivedCount = preg_match_all('/^Received:/im', $headers);
        if ($receivedCount < 2) {
            return true;
        }

        return false;
    }

    /**
     * Verify domain ownership via DNS
     */
    private function verifyDomain($email) {
        $domain = substr(strrchr($email, '@'), 1);

        // Check if domain has MX records
        $mxRecords = [];
        if (!getmxrr($domain, $mxRecords)) {
            return false;
        }

        return count($mxRecords) > 0;
    }

    /**
     * Log rejected email attempts
     */
    private function logRejection($emailId, $from, $reason) {
        if (!LOG_REJECTED_EMAILS) {
            return;
        }

        $timestamp = date('Y-m-d H:i:s');
        $logEntry = "[{$timestamp}] Email ID: {$emailId}, From: {$from}, Reason: {$reason}\n";

        file_put_contents($this->logFile, $logEntry, FILE_APPEND | LOCK_EX);
    }

    /**
     * Get validation summary for display
     */
    public function getValidationSummary($result) {
        $summary = "Sender: {$result['from']}\n";
        $summary .= "Status: " . ($result['valid'] ? '✓ VALID' : '✗ REJECTED') . "\n";

        if ($result['return_path']) {
            $summary .= "Return-Path: {$result['return_path']}\n";
        }

        if (CHECK_SPF) {
            $summary .= "SPF: " . ($result['spf_pass'] ? '✓ Pass' : '✗ Fail') . "\n";
        }

        if (CHECK_DKIM) {
            $summary .= "DKIM: " . ($result['dkim_pass'] ? '✓ Pass' : '✗ Fail') . "\n";
        }

        if (REQUIRE_AUTHENTICATION) {
            $summary .= "Authenticated: " . ($result['authenticated'] ? '✓ Yes' : '✗ No') . "\n";
        }

        if (!empty($result['reasons'])) {
            $summary .= "\nRejection Reasons:\n";
            foreach ($result['reasons'] as $reason) {
                $summary .= "  - {$reason}\n";
            }
        }

        return $summary;
    }
}