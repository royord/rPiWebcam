<?php
require_once __DIR__ . '/config.php';
require_once __DIR__ . '/email_checker.php';

class EmailBlogManager {
    private $dbFile;
    private $baseUrl;
    private $deleteTokenSecret;

    public function __construct() {
        $this->dbFile = defined('BLOG_DB_FILE') ? BLOG_DB_FILE : (__DIR__ . '/blog_posts.json');
        $this->baseUrl = defined('BLOG_BASE_URL') ? BLOG_BASE_URL : '';
        $this->deleteTokenSecret = defined('BLOG_DELETE_TOKEN_SECRET') ? BLOG_DELETE_TOKEN_SECRET : 'change-me';
    }

    public function handleRequest() {
        $action = $_GET['action'] ?? '';
        $format = $_GET['format'] ?? '';

        if ($action === 'check_email') {
            $this->requireEmailCheckToken();
            $summary = $this->checkEmailAndImportPosts();

            header('Content-Type: text/plain; charset=utf-8');
            echo "Email blog import complete.\n";
            echo "Processed: " . $summary['processed'] . "\n";
            echo "Created: " . $summary['created'] . "\n";
            echo "Edited: " . $summary['edited'] . "\n";
            echo "Delete requests: " . $summary['delete_requests'] . "\n";
            echo "Rejected: " . $summary['rejected'] . "\n";

            if ($summary['error'] !== '') {
                echo "Error: " . $summary['error'] . "\n";
            }

            return;
        }

        if ($action === 'confirm_delete') {
            $this->confirmDelete();
            return;
        }

        $this->checkEmailAndImportPostsIfDue();

        if ($format === 'xml') {
            $this->renderXml();
            return;
        }

        $this->renderBlog();
    }

    private function checkEmailAndImportPostsIfDue() {
        $db = $this->loadDb();

        $intervalSeconds = defined('BLOG_EMAIL_CHECK_INTERVAL_SECONDS')
            ? (int)BLOG_EMAIL_CHECK_INTERVAL_SECONDS
            : 900;

        $lastCheckedAt = $db['last_email_check_at'] ?? '';
        $lastCheckedTimestamp = $lastCheckedAt !== '' ? strtotime($lastCheckedAt) : false;

        if ($lastCheckedTimestamp !== false && (time() - $lastCheckedTimestamp) < $intervalSeconds) {
            return [
                'processed' => 0,
                'created' => 0,
                'edited' => 0,
                'delete_requests' => 0,
                'rejected' => 0,
                'error' => '',
                'skipped' => true
            ];
        }

        $summary = $this->checkEmailAndImportPosts();

        $db = $this->loadDb();
        $db['last_email_check_at'] = gmdate('c');
        $this->saveDb($db);

        $summary['skipped'] = false;

        return $summary;
    }

    private function requireEmailCheckToken() {
        $expectedToken = defined('BLOG_EMAIL_CHECK_TOKEN') ? BLOG_EMAIL_CHECK_TOKEN : '';

        if ($expectedToken === '' || !hash_equals($expectedToken, $_GET['token'] ?? '')) {
            http_response_code(403);
            header('Content-Type: text/plain; charset=utf-8');
            echo "Forbidden\n";
            exit;
        }
    }

    private function checkEmailAndImportPosts() {
        $summary = [
            'processed' => 0,
            'created' => 0,
            'edited' => 0,
            'delete_requests' => 0,
            'rejected' => 0,
            'error' => ''
        ];

        $checker = new EmailChecker();

        try {
            $checker->connect();
            $messages = $checker->getUnreadEmails();
            $checker->disconnect();
        } catch (Exception $ex) {
            $summary['error'] = $ex->getMessage();

            try {
                $checker->disconnect();
            } catch (Exception $disconnectException) {
                // Ignore disconnect errors.
            }

            return $summary;
        }

        $db = $this->loadDb();

        foreach ($messages as $message) {
            $summary['processed']++;

            if (!empty($message['rejected'])) {
                $summary['rejected']++;
                continue;
            }

            $subject = $this->plainText($message['subject'] ?? '');
            $body = (string)($message['body'] ?? '');
            $date = $this->plainText($message['date'] ?? '');
            $posterEmail = $this->extractPosterEmail($message);

            $command = $this->parseCommand($subject);

            if ($command['command'] === 'DELETE') {
                if ($this->requestDelete($db, $command['post_key'], $posterEmail)) {
                    $summary['delete_requests']++;
                }
                continue;
            }

            if ($command['command'] === 'EDIT') {
                if ($this->editPost($db, $command['post_key'], $subject, $body, $date, $posterEmail)) {
                    $summary['edited']++;
                }
                continue;
            }

            if ($this->createPost($db, $subject, $body, $date, $posterEmail)) {
                $summary['created']++;
            }
        }

        $this->saveDb($db);

        return $summary;
    }

    private function parseCommand($subject) {
        $subject = trim($subject);

        if (preg_match('/^DELETE\s+(.+)$/i', $subject, $matches)) {
            return [
                'command' => 'DELETE',
                'post_key' => trim($matches[1])
            ];
        }

        if (preg_match('/^EDIT\s+(.+)$/i', $subject, $matches)) {
            return [
                'command' => 'EDIT',
                'post_key' => trim($matches[1])
            ];
        }

        return [
            'command' => 'POST',
            'post_key' => null
        ];
    }

    private function createPost(&$db, $subject, $body, $date, $posterEmail) {
        $postKey = $this->makePostKey($date);

        if (isset($db['posts'][$postKey])) {
            $postKey .= '-' . substr(hash('sha256', $subject . $posterEmail . microtime(true)), 0, 8);
        }

        $now = gmdate('c');

        $db['posts'][$postKey] = [
            'key' => $postKey,
            'active' => true,
            'created_at' => $now,
            'updated_at' => $now,
            'email_date' => $date,
            'poster_email' => $posterEmail,
            'delete_requests' => [],
            'versions' => [
                [
                    'version' => 1,
                    'created_at' => $now,
                    'email_date' => $date,
                    'subject' => $subject,
                    'body' => $body
                ]
            ]
        ];

        return true;
    }

    private function editPost(&$db, $postKey, $subject, $body, $date, $posterEmail) {
        if (!isset($db['posts'][$postKey])) {
            return false;
        }

        if (!$this->isPosterAllowedForPost($db['posts'][$postKey], $posterEmail)) {
            return false;
        }

        $versionNumber = count($db['posts'][$postKey]['versions']) + 1;
        $now = gmdate('c');

        $db['posts'][$postKey]['versions'][] = [
            'version' => $versionNumber,
            'created_at' => $now,
            'email_date' => $date,
            'subject' => $this->removeCommandFromSubject($subject),
            'body' => $body
        ];

        $db['posts'][$postKey]['updated_at'] = $now;

        return true;
    }

    private function requestDelete(&$db, $postKey, $posterEmail) {
        if (!isset($db['posts'][$postKey])) {
            return false;
        }

        if (!$this->isPosterAllowedForPost($db['posts'][$postKey], $posterEmail)) {
            return false;
        }

        $token = $this->makeDeleteToken($postKey, $posterEmail);
        $confirmUrl = $this->baseUrl
            . '?action=confirm_delete'
            . '&post=' . rawurlencode($postKey)
            . '&email=' . rawurlencode($posterEmail)
            . '&token=' . rawurlencode($token);

        $db['posts'][$postKey]['delete_requests'][] = [
            'requested_at' => gmdate('c'),
            'requested_by' => $posterEmail,
            'confirmed' => false
        ];

        $this->sendDeleteConfirmationEmail($posterEmail, $postKey, $confirmUrl);

        return true;
    }

    private function confirmDelete() {
        $postKey = $_GET['post'] ?? '';
        $email = $_GET['email'] ?? '';
        $token = $_GET['token'] ?? '';

        header('Content-Type: text/html; charset=utf-8');

        if ($postKey === '' || $email === '' || $token === '') {
            http_response_code(400);
            echo "<p>Missing delete confirmation information.</p>";
            return;
        }

        $expectedToken = $this->makeDeleteToken($postKey, $email);

        if (!hash_equals($expectedToken, $token)) {
            http_response_code(403);
            echo "<p>Invalid or expired delete confirmation link.</p>";
            return;
        }

        $db = $this->loadDb();

        if (!isset($db['posts'][$postKey])) {
            http_response_code(404);
            echo "<p>Post not found.</p>";
            return;
        }

        if (!$this->isPosterAllowedForPost($db['posts'][$postKey], $email)) {
            http_response_code(403);
            echo "<p>You are not allowed to delete this post.</p>";
            return;
        }

        $db['posts'][$postKey]['active'] = false;
        $db['posts'][$postKey]['deleted_at'] = gmdate('c');
        $db['posts'][$postKey]['deleted_by'] = $email;

        foreach ($db['posts'][$postKey]['delete_requests'] as &$request) {
            if (($request['requested_by'] ?? '') === $email) {
                $request['confirmed'] = true;
                $request['confirmed_at'] = gmdate('c');
            }
        }

        $this->saveDb($db);

        echo "<p>Post deleted successfully.</p>";
        echo "<p><a href=\"" . htmlspecialchars($this->baseUrl, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8') . "\">Return to blog</a></p>";
    }

    private function renderBlog() {
        $db = $this->loadDb();
        $page = max(1, (int)($_GET['page'] ?? 1));
        $perPage = 10;

        $posts = array_values($db['posts'] ?? []);

        $posts = array_filter($posts, function ($post) {
            return !empty($post['active']);
        });

        usort($posts, function ($a, $b) {
            return strcmp($b['created_at'] ?? '', $a['created_at'] ?? '');
        });

        $totalPosts = count($posts);
        $totalPages = max(1, (int)ceil($totalPosts / $perPage));
        $page = min($page, $totalPages);
        $offset = ($page - 1) * $perPage;
        $postsForPage = array_slice($posts, $offset, $perPage);

        header('Content-Type: text/html; charset=utf-8');

        echo "<!DOCTYPE html>";
        echo "<html lang=\"en\">";
        echo "<head>";
        echo "<meta charset=\"UTF-8\">";
        echo "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">";
        echo "<title>Email Blog</title>";
        echo "<style>";
        echo "body{font-family:Arial,sans-serif;max-width:900px;margin:30px auto;padding:0 15px;line-height:1.5;}";
        echo "article{border-bottom:1px solid #ccc;padding:20px 0;}";
        echo ".date{color:#666;font-size:.9em;}";
        echo ".key{color:#777;font-size:.85em;}";
        echo ".pagination a,.pagination strong{margin-right:8px;}";
        echo "</style>";
        echo "</head>";
        echo "<body>";
        echo "<h1>Email Blog</h1>";
        echo "<p><a href=\"?format=xml\">XML Feed</a></p>";

        if (empty($postsForPage)) {
            echo "<p>No posts yet.</p>";
        }

        foreach ($postsForPage as $post) {
            $version = $this->latestVersion($post);

            echo "<article>";
            echo "<h2>" . htmlspecialchars($version['subject'] ?? '', ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8') . "</h2>";
            echo "<div class=\"date\">" . htmlspecialchars($post['email_date'] ?? '', ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8') . "</div>";
            echo "<div class=\"key\">Post key: " . htmlspecialchars($post['key'] ?? '', ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8') . "</div>";
            echo "<div class=\"body\">" . ($version['body'] ?? '') . "</div>";
            echo "</article>";
        }

        echo "<div class=\"pagination\">";

        for ($i = 1; $i <= $totalPages; $i++) {
            if ($i === $page) {
                echo "<strong>$i</strong>";
            } else {
                echo "<a href=\"?page=$i\">$i</a>";
            }
        }

        echo "</div>";
        echo "</body>";
        echo "</html>";
    }

    private function renderXml() {
        $db = $this->loadDb();
        $posts = array_values($db['posts'] ?? []);

        $posts = array_filter($posts, function ($post) {
            return !empty($post['active']);
        });

        usort($posts, function ($a, $b) {
            return strcmp($b['created_at'] ?? '', $a['created_at'] ?? '');
        });

        header('Content-Type: application/xml; charset=utf-8');

        $xml = new SimpleXMLElement('<?xml version="1.0" encoding="UTF-8"?><blog></blog>');

        foreach ($posts as $post) {
            $version = $this->latestVersion($post);
            $postNode = $xml->addChild('post');

            $postNode->addChild('key', htmlspecialchars($post['key'] ?? '', ENT_XML1, 'UTF-8'));
            $postNode->addChild('active', !empty($post['active']) ? 'true' : 'false');
            $postNode->addChild('date', htmlspecialchars($post['email_date'] ?? '', ENT_XML1, 'UTF-8'));
            $postNode->addChild('poster_email', htmlspecialchars($post['poster_email'] ?? '', ENT_XML1, 'UTF-8'));
            $postNode->addChild('subject', htmlspecialchars($version['subject'] ?? '', ENT_XML1, 'UTF-8'));

            $bodyNode = $postNode->addChild('body');
            $bodyNode[0] = htmlspecialchars(strip_tags($version['body'] ?? ''), ENT_XML1, 'UTF-8');
        }

        echo $xml->asXML();
    }

    private function loadDb() {
        if (!file_exists($this->dbFile)) {
            return [
                'version' => 1,
                'posts' => []
            ];
        }

        $json = file_get_contents($this->dbFile);
        $db = json_decode($json, true);

        if (!is_array($db)) {
            return [
                'version' => 1,
                'posts' => []
            ];
        }

        if (!isset($db['posts']) || !is_array($db['posts'])) {
            $db['posts'] = [];
        }

        return $db;
    }

    private function saveDb($db) {
        $dir = dirname($this->dbFile);

        if (!is_dir($dir)) {
            mkdir($dir, 0755, true);
        }

        $tempFile = $this->dbFile . '.tmp';

        file_put_contents(
            $tempFile,
            json_encode($db, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE),
            LOCK_EX
        );

        rename($tempFile, $this->dbFile);
    }

    private function makePostKey($date) {
        $timestamp = strtotime($date);

        if ($timestamp === false) {
            $timestamp = time();
        }

        return gmdate('Ymd_His', $timestamp);
    }

    private function latestVersion($post) {
        $versions = $post['versions'] ?? [];

        if (empty($versions)) {
            return [
                'subject' => '',
                'body' => ''
            ];
        }

        return $versions[count($versions) - 1];
    }

    private function makeDeleteToken($postKey, $email) {
        return hash_hmac('sha256', $postKey . '|' . strtolower($email), $this->deleteTokenSecret);
    }

    private function sendDeleteConfirmationEmail($to, $postKey, $confirmUrl) {
        $subject = "Confirm delete for blog post $postKey";

        $message = "A delete request was received for blog post:\n\n";
        $message .= "$postKey\n\n";
        $message .= "Click this link to confirm deletion:\n\n";
        $message .= "$confirmUrl\n\n";
        $message .= "If you did not request this, ignore this email.\n";

        $headers = [];

        if (defined('BLOG_EMAIL_FROM') && BLOG_EMAIL_FROM !== '') {
            $headers[] = 'From: ' . BLOG_EMAIL_FROM;
        }

        $headers[] = 'Content-Type: text/plain; charset=UTF-8';

        @mail($to, $subject, $message, implode("\r\n", $headers));
    }

    private function isPosterAllowedForPost($post, $email) {
        return strtolower($post['poster_email'] ?? '') === strtolower($email);
    }

    private function removeCommandFromSubject($subject) {
        return preg_replace('/^(EDIT|DELETE)\s+.+$/i', 'Updated Post', trim($subject));
    }

    private function plainText($value) {
        return trim(html_entity_decode(strip_tags((string)$value), ENT_QUOTES | ENT_HTML5, 'UTF-8'));
    }

    private function extractPosterEmail($message) {
        $from = $message['validation']['from'] ?? ($message['from'] ?? '');
        $from = $this->plainText($from);

        if (preg_match('/<([^>]+)>/', $from, $matches)) {
            return strtolower(trim($matches[1]));
        }

        if (filter_var($from, FILTER_VALIDATE_EMAIL)) {
            return strtolower($from);
        }

        if (preg_match('/[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}/i', $from, $matches)) {
            return strtolower($matches[0]);
        }

        return '';
    }
}

$manager = new EmailBlogManager();
$manager->handleRequest();
