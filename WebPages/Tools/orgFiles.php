<?php
ob_start();
// Get current date
$currentDate = date('Y-m');

// Extract year and month
$current_year = date('Y');
$current_month = date('m');

echo "Current calendar Year/Month\n";
echo "Year: $current_year\n";
echo "Month: $current_month\n";

// Set the source directory containing the image files
//$sourceDir = './images/'; // Adjust this path as needed
$sourceDir = 'cameras/camera1'; // Adjust this path as needed
//$targetBaseDir = './organized_images/'; // Base directory for organized files
$targetBaseDir = 'cameras/camera1'; // Base directory for organized files

// Ensure the source directory exists
if (!is_dir($sourceDir)) {
    die("Source directory does not exist: $sourceDir");
}

// Create the target base directory if it doesn't exist
if (!is_dir($targetBaseDir)) {
    mkdir($targetBaseDir, 0644, true);
}

// Function to extract year and month from filename
function getYearMonthFromFilename($filename) {
    // Match pattern like image20240124_150057
    if (preg_match('/image(\d{4})(\d{2})\d{2}_\d{6}/', $filename, $matches)) {
        return [
            'year' => $matches[1],
            'month' => $matches[2]
        ];
    }
    return false;
}

// Read files in the source directory
$files = scandir($sourceDir);

foreach ($files as $file) {
    // Skip . and .. directories
    if ($file === '.' || $file === '..') {
        continue;
    }

    // Extract year and month from filename
    $dateInfo = getYearMonthFromFilename($file);

    if ($dateInfo) {
        $year = $dateInfo['year'];
        $month = $dateInfo['month'];

        if($year == $current_year and $month == $current_month){
            break;
        }

        // Create year directory
        $yearDir = $targetBaseDir . $year . '/';
        if (!is_dir($yearDir)) {
            mkdir($yearDir, 0644, true);
        }

        // Create month directory
        $monthDir = $yearDir . $month . '/';
        if (!is_dir($monthDir)) {
            mkdir($monthDir, 0644, true);
        }

        // Move the file to the appropriate directory
        $sourcePath = $sourceDir . $file;
        $targetPath = $monthDir . $file;

        $sourceFileSize = filesize($sourcePath);
        // Optionally, convert to human-readable format
        $units = ['B', 'KB', 'MB', 'GB', 'TB'];
        $size = $sourceFileSize;
        $unitIndex = 0;

        while ($size >= 1024 && $unitIndex < count($units) - 1) {
            $size /= 1024;
            $unitIndex++;
        }

        echo "$sourceFileSize";
        if ($sourceFileSize > 80000){
            if (rename($sourcePath, $targetPath)) {
                echo "Moved $file to $targetPath\n";
            } else {
                echo "Failed to move $file\n";
            }
        }
        else {
            // File to be deleted
            echo "$sourcePath  DELETED\n";
            unlink($sourcePath);
        }

    } else {
        echo "Skipping $file: Invalid filename format\n";
    }
}

echo "File organization complete.\n";

?>