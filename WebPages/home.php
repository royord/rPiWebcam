<?php
function asset2($path) {
    $full = $_SERVER['DOCUMENT_ROOT'] . $path;
    $version = file_exists($full) ? filemtime($full) : time();
    return $path . '?v=' . $version;
}
?>
<section id="custom_html-2" class="widget_text widget widget-1 even widget-first widget_custom_html">
    <div class="widget_text widget-wrap">
        <div class="textwidget custom-html-widget">
            <h3>Camera1</h3>
            <img src="<?= asset2('cameras/cameraname1/live.jpg') ?>" width="100%">
        </div>
    </div>
</section>
<br>
<section id="custom_html-2" class="widget_text widget widget-1 even widget-first widget_custom_html">
    <div class="widget_text widget-wrap">
        <div class="textwidget custom-html-widget">
            <h3>Camera2</h3>
            <img src="cameras/cameraname2/live.jpg" width="100%">
        </div>
    </div>
</section>