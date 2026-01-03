<?php
// liveResize.php provided in order to resize the live.jpg image
// this has been included
// Following are examples that can be used for embedding
/*
    <!-- Simple image tag -->
    <img src="liveResize.php?width=800&height=600" alt="Resized Image">

    <!-- Responsive image -->
    <img src="liveResize.php?width=400&height=300"
         srcset="liveResize.php?width=800&height=600 2x"
         alt="Resized Image">

    <!-- Multiple sizes -->
    <picture>
        <source media="(min-width: 1200px)" srcset="liveResize.php?width=1200&height=800">
        <source media="(min-width: 768px)" srcset="liveResize.php?width=800&height=600">
        <img src="liveResize.php?width=400&height=300" alt="Resized Image">
    </picture>

    <!-- As background image in CSS -->
    <div style="background-image: url('liveResize.php?width=1920&height=1080');"></div>
*/
// Check if parameters are provided via URL
if (
        1==1
        && isset($_GET['width'])
        && isset($_GET['height'])
        // && isset($_GET['input']) // Parameter Removed as we're only going to
        // size the "live.jpg" image at this point
) {
    //$inputFile = $_GET['input'];
    $inputFile = "./live.jpg";
    $targetWidth = intval($_GET['width']);
    $targetHeight = intval($_GET['height']);

    // Validate input
    if ($targetWidth <= 0 || $targetHeight <= 0) {
        header('HTTP/1.1 400 Bad Request');
        die('Width and height must be positive numbers.');
    }

    // Check if input file exists
    if (!file_exists($inputFile)) {
        header('HTTP/1.1 404 Not Found');
        die('Input file does not exist.');
    }

    // Cache configuration
    $cacheDir = __DIR__ . '/cache/';
    if (!is_dir($cacheDir)) {
        mkdir($cacheDir, 0755, true);
    }

    $cacheFile = $cacheDir . md5($inputFile . $targetWidth . $targetHeight) . '.jpg';

    // Check if cache exists and is newer than source file
    if (file_exists($cacheFile) && filemtime($cacheFile) >= filemtime($inputFile)) {
        // Serve from cache
        header('Content-Type: image/jpeg');
        header('Cache-Control: public, max-age=86400');
        header('Last-Modified: ' . gmdate('D, d M Y H:i:s', filemtime($cacheFile)) . ' GMT');
        readfile($cacheFile);
        exit;
    }

    // Get image info
    $imageInfo = getimagesize($inputFile);

    if ($imageInfo === false) {
        header('HTTP/1.1 400 Bad Request');
        die('Invalid image file.');
    }

    $mimeType = $imageInfo['mime'];

    // Create image resource based on type
    switch ($mimeType) {
        case 'image/jpeg':
            $sourceImage = imagecreatefromjpeg($inputFile);
            break;
        case 'image/png':
            $sourceImage = imagecreatefrompng($inputFile);
            break;
        case 'image/gif':
            $sourceImage = imagecreatefromgif($inputFile);
            break;
        case 'image/webp':
            $sourceImage = imagecreatefromwebp($inputFile);
            break;
        default:
            header('HTTP/1.1 400 Bad Request');
            die('Unsupported image format. Please use JPG, PNG, GIF, or WebP.');
    }

    if ($sourceImage) {
        // Create new image with target dimensions
        $resizedImage = imagecreatetruecolor($targetWidth, $targetHeight);

        // Preserve transparency for PNG
        if ($mimeType === 'image/png') {
            imagealphablending($resizedImage, false);
            imagesavealpha($resizedImage, true);
        }

        // Resize the image
        imagecopyresampled(
            $resizedImage,
            $sourceImage,
            0, 0, 0, 0,
            $targetWidth,
            $targetHeight,
            imagesx($sourceImage),
            imagesy($sourceImage)
        );

        // Save to cache
        imagejpeg($resizedImage, $cacheFile, 90);

        // Set the cache file timestamp to match the source file
        touch($cacheFile, filemtime($inputFile));

        // Output to browser
        header('Content-Type: image/jpeg');
        header('Cache-Control: public, max-age=86400');
        header('Last-Modified: ' . gmdate('D, d M Y H:i:s', filemtime($inputFile)) . ' GMT');

        imagejpeg($resizedImage, null, 90);

        // Clean up
        imagedestroy($sourceImage);
        imagedestroy($resizedImage);
    }
} else {
    header('HTTP/1.1 400 Bad Request');
    die('Missing required parameters: input, width, height');
}
?>