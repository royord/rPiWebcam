<?php
// email_checker_validated.php - With whitelist validation
require_once 'config.php';
require_once 'enhanced_sanitizer.php';
require_once 'email_validator.php';

class EmailChecker {
    private $inbox;
    private $sanitizer;
    private $validator;

    public function __construct() {
        $this->sanitizer = new EnhancedSanitizer();
        $this->validator = new EmailValidator(ALLOWED_SENDERS);
    }

    public function connect() {
        $mailbox = '{' . EMAIL_HOST . ':' . EMAIL_PORT . '/imap/' . EMAIL_ENCRYPTION . '}INBOX';

        $this->inbox = imap_open(
            $mailbox,
            EMAIL_USERNAME,
            EMAIL_PASSWORD
        );

        if (!$this->inbox) {
            throw new Exception('Cannot connect: ' . imap_last_error());
        }

        return true;
    }

    public function getUnreadEmails() {
        $emails = imap_search($this->inbox, 'UNSEEN');

        if (!$emails) {
            return [];
        }

        $messages = [];

        foreach ($emails as $emailId) {
            // Validate sender first
            $validation = $this->validator->validateSender($emailId, $this->inbox);

            // Only process valid emails
            if (!$validation['valid']) {
                // Mark as read to prevent reprocessing
                $this->markAsRead($emailId);

                // Add to messages with rejection info
                $messages[] = [
                    'id' => $emailId,
                    'rejected' => true,
                    'from' => $validation['from'],
                    'validation' => $validation,
                    'summary' => $this->validator->getValidationSummary($validation)
                ];

                continue;
            }

            // Process valid email
            $header = imap_headerinfo($this->inbox, $emailId);

            $messages[] = [
                'id' => $emailId,
                'rejected' => false,
                'from' => $this->decodeHeader($header->fromaddress),
                'subject' => $this->decodeHeader($header->subject),
                'date' => $this->sanitizer->sanitizeText($header->date),
                'body' => $this->getBody($emailId),
                'validation' => $validation
            ];
        }

        return $messages;
    }

    /**
     * Decode MIME encoded headers
     */
    private function decodeHeader($header) {
        $decoded = imap_mime_header_decode($header);

        $result = '';
        foreach ($decoded as $part) {
            $charset = ($part->charset === 'default') ? 'UTF-8' : $part->charset;

            if (strtoupper($charset) !== 'UTF-8') {
                $text = mb_convert_encoding($part->text, 'UTF-8', $charset);
            } else {
                $text = $part->text;
            }

            $result .= $text;
        }

        return $this->sanitizer->sanitizeText($result);
    }

    private function getBody($emailId) {
        $structure = imap_fetchstructure($this->inbox, $emailId);

        $body = $this->getBodyPart($emailId, $structure, 'HTML');

        if (empty($body)) {
            $body = $this->getBodyPart($emailI