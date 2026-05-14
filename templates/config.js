// Tab switching (right pane only)
function switchTab(e, tabId) {
    e.currentTarget.closest('.settings-pane').querySelectorAll('.tab-content').forEach(function(t) { t.classList.remove('active'); });
    e.currentTarget.closest('.settings-pane').querySelectorAll('.tab-btn').forEach(function(b) { b.classList.remove('active'); });
    document.getElementById(tabId).classList.add('active');
    e.currentTarget.classList.add('active');
    // Persist active tab for form submission and localStorage
    var name = tabId.replace('tab-', '');
    try { document.getElementById('_active_tab').value = name; localStorage.setItem('configActiveTab', name); } catch(e) {}
}

// Capture mode switching
(function() {
    var modeSelect = document.getElementById('capture_mode');
    if (modeSelect) {
        function updateMode() {
            var mode = modeSelect.value;
            var intervalFields = document.getElementById('interval-fields');
            var timedFields = document.getElementById('timed-fields');
            var ssFields = document.getElementById('sunrise-sunset-fields');

            // Show/hide field groups
            intervalFields.style.display = (mode === 'interval') ? 'block' : 'none';
            timedFields.style.display = (mode === 'timed') ? 'block' : 'none';
            ssFields.style.display = (mode === 'sunrise_sunset') ? 'block' : 'none';

            // Enable only the active field group, disable others
            var activeFields = mode === 'interval' ? intervalFields : (mode === 'timed' ? timedFields : ssFields);
            var inactiveFields = mode === 'interval' ? [timedFields, ssFields] :
                                 (mode === 'timed' ? [intervalFields, ssFields] : [intervalFields, timedFields]);

            // Disable inactive fields
            inactiveFields.forEach(function(f) {
                var inputs = f.querySelectorAll('input, select, textarea');
                inputs.forEach(function(inp) { inp.disabled = true; });
            });

            // Enable active fields
            var inputs = activeFields.querySelectorAll('input, select, textarea');
            inputs.forEach(function(inp) { inp.disabled = false; });
        }
        modeSelect.addEventListener('change', updateMode);
        updateMode();
    }
})();

// Timed schedule entry management
var timedEntryCounter = 0;
function addTimedEntry(value) {
    var container = document.getElementById('timed-entries');
    timedEntryCounter++;
    var div = document.createElement('div');
    div.style.cssText = 'display:flex;gap:8px;margin-bottom:6px;align-items:center;';
    div.id = 'timed-entry-' + timedEntryCounter;
    var input = document.createElement('input');
    input.type = 'text';
    input.name = 'timed_time_' + timedEntryCounter;
    input.className = 'timed-input';
    input.placeholder = 'HH:MM';
    input.maxLength = 5;
    input.style.cssText = 'flex:1;padding:6px 10px;border:1px solid #ced4da;border-radius:4px;font-size:14px;';
    if (value) input.value = value;
    var removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.className = 'btn';
    removeBtn.style.cssText = 'background:#dc3545;color:#fff;padding:6px 12px;border:none;border-radius:4px;cursor:pointer;';
    removeBtn.textContent = '×';
    removeBtn.onclick = function() { div.remove(); };
    div.appendChild(input);
    div.appendChild(removeBtn);
    container.appendChild(div);
}

function serializeTimedEntries() {
    var inputs = document.querySelectorAll('.timed-input');
    var times = [];
    inputs.forEach(function(inp) {
        if (inp.value.trim()) times.push(inp.value.trim());
    });
    document.getElementById('timed_schedule').value = JSON.stringify(times);
}

// Grid square auto-conversion
(function() {
    var gsInput = document.getElementById('grid_square');
    if (gsInput) {
        gsInput.addEventListener('change', function() {
            var val = gsInput.value.trim();
            if (val.length >= 2) {
                var result = null;
                try {
                    // Inline grid conversion
                    var gs = val.toUpperCase();
                    if (gs.length >= 2) {
                        var lon = -180 + (gs.charCodeAt(0) - 65) * 20;
                        var lat = -90 + (gs.charCodeAt(1) - 65) * 10;
                        if (gs.length >= 4) {
                            lon += (parseInt(gs[2]) || 0) * 2;
                            lat += (parseInt(gs[3]) || 0) * 1;
                        }
                        if (gs.length >= 6) {
                            lon += (gs.charCodeAt(4) - 65) * (5.0 / 60.0);
                            lat += (gs.charCodeAt(5) - 65) * (2.5 / 60.0);
                        }
                        result = [lat, lon];
                    }
                } catch(e) {}
                if (result) {
                    document.getElementById('lat').value = result[0].toFixed(4);
                    document.getElementById('lon').value = result[1].toFixed(4);
                }
            }
        });
    }
})();

// Save button: AJAX save then reload page
(function() {
    var saveBtn = document.getElementById('saveBtn');
    if (saveBtn) {
        saveBtn.addEventListener('click', function() {
            serializeTimedEntries();
            // Validate capture mode is set
            var mode = document.getElementById('capture_mode').value;
            if (!mode || !['interval', 'timed', 'sunrise_sunset'].includes(mode)) {
                alert('Please select a capture mode (interval, timed, or sunrise/sunset).');
                return;
            }
            // Validate timed mode has at least one entry
            if (mode === 'timed') {
                var entries = document.querySelectorAll('.timed-input');
                if (entries.length === 0) {
                    alert('Please add at least one time for timed capture mode.');
                    return;
                }
            }
            var form = document.getElementById('configForm');
            var fd = new FormData(form);
            saveBtn.disabled = true;
            saveBtn.textContent = 'Saving...';
            fetch('/save_config', {
                method: 'POST',
                body: fd
            }).then(function(r) {
                if (r.status === 200) {
                    // Show toast, then reload to refresh all values
                    var toast = document.createElement('div');
                    toast.className = 'toast';
                    toast.textContent = 'Configuration saved!';
                    document.body.appendChild(toast);
                    requestAnimationFrame(function() { toast.classList.add('show'); });
                    setTimeout(function() {
                        toast.classList.remove('show');
                        setTimeout(function() { toast.remove(); }, 400);
                    }, 2000);
                    window.location.reload();
                } else {
                    return r.text().then(function(t) { alert('Save failed: ' + t); }, function() { alert('Save failed'); });
                }
            }).catch(function(e) {
                alert('Save failed: ' + e.message);
            }).finally(function() {
                saveBtn.disabled = false;
                saveBtn.textContent = 'Save Configuration';
            });
        });
    }
})();

// Initialize timed schedule entries from saved config
(function() {
    try {
        var saved = document.getElementById('timed_schedule').value;
        if (saved && saved !== '[]') {
            var times = JSON.parse(saved);
            times.forEach(function(t) { addTimedEntry(t); });
        }
    } catch(e) {}
})();

// Restore tab and show toast on load
(function() {
    var params = new URLSearchParams(window.location.search);
    var saved = params.get('saved');
    var tabParam = params.get('tab');

    // Show toast for save/import
    if (saved === '1') {
        var toast = document.createElement('div');
        toast.id = 'saveToast';
        toast.className = 'toast';
        toast.textContent = 'Configuration saved!';
        document.body.appendChild(toast);
        requestAnimationFrame(function() { toast.classList.add('show'); });
        setTimeout(function() {
            toast.classList.remove('show');
            setTimeout(function() { toast.remove(); }, 400);
        }, 5000);
        // Clear the saved param so toast doesn't reappear on accidental refresh
        var url = new URL(window.location);
        url.searchParams.delete('saved');
        if (url.searchParams.get('tab')) url.searchParams.delete('tab');
        window.history.replaceState({}, '', url);
    }
    if (params.get('imported') === '1') {
        var toast = document.createElement('div');
        toast.id = 'saveToast';
        toast.className = 'toast';
        toast.textContent = 'Configuration imported successfully!';
        document.body.appendChild(toast);
        requestAnimationFrame(function() { toast.classList.add('show'); });
        setTimeout(function() {
            toast.classList.remove('show');
            setTimeout(function() { toast.remove(); }, 400);
        }, 5000);
        var url = new URL(window.location);
        url.searchParams.delete('imported');
        if (url.searchParams.get('tab')) url.searchParams.delete('tab');
        window.history.replaceState({}, '', url);
    }

    // Restore active tab: URL param > localStorage > default 'camera'
    var activeTab = null;
    if (tabParam) activeTab = tabParam;
    else {
        try { activeTab = localStorage.getItem('configActiveTab'); } catch(e) {}
    }
    if (!activeTab) activeTab = 'camera';

    // Always sync hidden field
    try { document.getElementById('_active_tab').value = activeTab; } catch(e) {}

    if (activeTab !== 'camera') {
        var btns = document.querySelector('.settings-pane').querySelectorAll('.tab-btn');
        var contents = document.querySelector('.settings-pane').querySelectorAll('.tab-content');
        btns.forEach(function(b) { b.classList.remove('active'); });
        contents.forEach(function(t) { t.classList.remove('active'); });
        var target = document.getElementById('tab-' + activeTab);
        if (target) {
            target.classList.add('active');
            for (var i = 0; i < btns.length; i++) {
                if (btns[i].getAttribute('onclick') && btns[i].getAttribute('onclick').indexOf("'tab-" + activeTab + "')") > -1) {
                    btns[i].classList.add('active');
                    break;
                }
            }
        }
    }
})();

// Import modal
(function() {
    var modal = document.getElementById('importModal');
    var openBtn = document.getElementById('openImportBtn');
    var closeBtn = document.getElementById('closeImportBtn');
    openBtn.onclick = function() { modal.style.display = 'block'; };
    closeBtn.onclick = function() { modal.style.display = 'none'; };
    window.onclick = function(e) { if (e.target === modal) modal.style.display = 'none'; };
})();

// Disk usage gauge (updates every 10 seconds)
(function() {
    function updateStorage() {
        fetch('/disk_usage')
            .then(function(r) { return r.json(); })
            .then(function(d) {
                var fill = document.getElementById('storageFill');
                var usedEl = document.getElementById('storageUsed');
                var freeEl = document.getElementById('storageFree');
                var totalEl = document.getElementById('storageTotal');
                if (!fill) return;
                fill.style.width = d.percent + '%';
                fill.className = 'storage-fill' + (d.percent >= 90 ? ' crit' : d.percent >= 70 ? ' warn' : '');
                usedEl.textContent = d.used_gb.toFixed(1) + ' GB';
                freeEl.textContent = d.free_gb.toFixed(1) + ' GB free';
                totalEl.textContent = 'of ' + d.total_gb.toFixed(1) + ' GB';
                // Update archive info if elements exist
                var archiveEl = document.getElementById('archiveInfo');
                if (archiveEl) {
                    archiveEl.textContent = d.total_images + ' images total, ' + d.archive_images + ' eligible for cleanup';
                }
            })
            .catch(function() {});
    }
    updateStorage();
    setInterval(updateStorage, 10000);
})();

// Cleanup button handler
(function() {
    var cleanupBtn = document.getElementById('cleanupBtn');
    var resultDiv = document.getElementById('cleanupResult');
    if (cleanupBtn) {
        cleanupBtn.addEventListener('click', function() {
            cleanupBtn.disabled = true;
            cleanupBtn.textContent = 'Cleaning up...';
            if (resultDiv) {
                resultDiv.style.display = 'block';
                resultDiv.className = 'cleanup-result';
                resultDiv.textContent = 'Running cleanup...';
            }
            fetch('/cleanup_disk')
                .then(function(r) { return r.json(); })
                .then(function(d) {
                    if (resultDiv) {
                        resultDiv.className = 'cleanup-result ok';
                        var freedMB = (d.freed_bytes / (1024*1024)).toFixed(1);
                        resultDiv.textContent = 'Cleaned up: ' + d.deleted + ' image(s) deleted, ' + freedMB + ' MB freed.';
                    }
                })
                .catch(function(e) {
                    if (resultDiv) {
                        resultDiv.className = 'cleanup-result error';
                        resultDiv.textContent = 'Error: ' + e.message;
                    }
                })
                .finally(function() {
                    cleanupBtn.disabled = false;
                    cleanupBtn.textContent = 'Run Cleanup Now';
                });
        });
    }
})();

// Unsaved-changes guard
(function() {
    var originalValues = {
        'ftp-mode': 'cfg.ftp_mode',
        'ftp-server': 'cfg.ftp_server',
        'ftp-port': 'cfg.ftp_port',
        'ftp-username': 'cfg.ftp_username',
        'camera_name': 'cfg.camera_name',
        'rotation': 'cfg.rotation',
        'capture_mode': 'cfg.capture_mode',
        'time_before_first_image': 'cfg.time_before_first_image',
        'time_before_image': 'cfg.time_before_image',
        'timed_schedule': 'cfg.timed_schedule',
        'output_width': 'cfg.output_width',
        'output_height': 'cfg.output_height',
        'output_extension': 'cfg.output_extension',
        'embed_timestamp': cfg.embed_timestamp === 'true' || cfg.embed_timestamp === true ? 'true' : 'false',
        'embed_camera_name': cfg.embed_camera_name === 'true' || cfg.embed_camera_name === true ? 'true' : 'false',
        'archive_retention_days': 'cfg.archive_retention_days',
        'reserved_space_gb': 'cfg.reserved_space_gb',
        'file_name': 'cfg.file_name',
        'text_size': 'cfg.text_size',
        'text_color': 'cfg.text_color',
        'text_background': 'cfg.text_background',
        'camera_timezone': 'cfg.camera_timezone',
        'camera_daylight_savings': cfg.camera_daylight_savings === 'true' || cfg.camera_daylight_savings === true ? 'true' : 'false',
        'camera_port': 'cfg.camera_port',
        'camera_url': 'cfg.camera_url',
        'sunrise_offset': 'cfg.sunrise_offset',
        'sunset_offset': 'cfg.sunset_offset',
        'grid_square': 'cfg.grid_square',
        'lat': 'cfg.lat',
        'lon': 'cfg.lon',
    };
    var hasChanges = false;

    document.getElementById('configForm').addEventListener('input', function(e) { hasChanges = true; }, true);
    document.getElementById('configForm').addEventListener('change', function(e) { hasChanges = true; }, true);

    window.addEventListener('beforeunload', function(e) {
        if (hasChanges) {
            e.preventDefault();
            e.returnValue = '';
        }
    });

    var params = new URLSearchParams(window.location.search);
    if (params.get('saved') === '1' || params.get('imported') === '1') {
        hasChanges = false;
    }
})();

// RTC warning: poll /rtc_status and show/hide banner
(function() {
    function updateRtcWarning() {
        fetch('/rtc_status')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                var banner = document.getElementById('rtc-warning');
                var msg = document.getElementById('rtc-warning-msg');
                if (!banner || !msg) return;
                if (data.has_warning) {
                    msg.textContent = 'The battery/RTC may need to be replaced. RTC update on ' + data.last_error + ' found the RTC >2 hours out of date. Error count: ' + data.error_count;
                    banner.style.display = 'block';
                } else {
                    banner.style.display = 'none';
                }
            })
            .catch(function() {});  // Ignore errors (no RTC, server error, etc.)
    }
    // Poll on load, then every 15 minutes
    updateRtcWarning();
    setInterval(updateRtcWarning, 15 * 60 * 1000);
})();

</script>
</body>
</html>
