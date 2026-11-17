package local.apply;

import android.Manifest;
import android.app.*;
import android.content.*;
import android.net.Uri;
import android.os.*;
import android.provider.Settings;
import android.webkit.*;
import android.widget.*;
import android.view.View;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.Map;

public class MainActivity extends Activity {
    private static final String ORIGIN = "https://appassets.androidplatform.net";
    private final Handler handler = new Handler(Looper.getMainLooper());
    private WebView web;
    private TextView status;
    private Button permissions;
    private boolean loaded;
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(0, 0, 0, 0);
        layout.setOnApplyWindowInsetsListener((v, insets) -> {
            var bars = insets.getInsets(android.view.WindowInsets.Type.systemBars());
            v.setPadding(bars.left, bars.top, bars.right, bars.bottom);
            return insets;
        });
        status = new TextView(this);
        status.setText("Запускаем Apply…");
        status.setPadding(20, 12, 20, 12);
        layout.addView(status);
        permissions = new Button(this);
        permissions.setText("Разрешить уведомления Apply");
        permissions.setOnClickListener(v -> startActivity(new Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, getPackageName())));
        layout.addView(permissions);
        web = new WebView(this);
        layout.addView(web, new LinearLayout.LayoutParams(-1, 0, 1));
        setContentView(layout);
        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setJavaScriptCanOpenWindowsAutomatically(false);
        web.addJavascriptInterface(new Bridge(), "ApplyAndroid");
        web.setWebViewClient(new WebViewClient() {
            @Override public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                String path = uri.getPath();
                if ("https".equals(uri.getScheme()) && "appassets.androidplatform.net".equals(uri.getHost())
                    && path != null && path.startsWith("/ui/") && !path.contains("..") && !path.contains("\\")) {
                    try {
                        String mime = path.endsWith(".html") ? "text/html" : path.endsWith(".js") ? "application/javascript" : path.endsWith(".css") ? "text/css" : path.endsWith(".svg") ? "image/svg+xml" : "application/octet-stream";
                        return new WebResourceResponse(mime, "UTF-8", 200, "OK", Map.of(
                            "Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'none'; object-src 'none'; frame-src 'none'; base-uri 'none'",
                            "X-Content-Type-Options", "nosniff"), getAssets().open(path.substring(1)));
                    } catch (IOException ignored) {}
                }
                return new WebResourceResponse("text/plain", "UTF-8", 403, "Forbidden", Map.of(), new ByteArrayInputStream(new byte[0]));
            }
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                if (request.getUrl().toString().startsWith(ORIGIN + "/ui/")) return false;
                RunService service = RunService.instance;
                if (service != null) service.openExternal(request.getUrl().toString());
                return true;
            }
        });
        if (!getSystemService(NotificationManager.class).areNotificationsEnabled())
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 1);
    }
    public class Bridge {
        @JavascriptInterface public String request(String path, String body) {
            RunService service = RunService.instance;
            return service == null ? "{\"ok\":false,\"error\":\"Откройте Apply заново.\"}" : service.request(path, body);
        }
    }
    private final Runnable refresh = new Runnable() {
        @Override public void run() {
            permissions.setVisibility(getSystemService(NotificationManager.class).areNotificationsEnabled() ? View.GONE : View.VISIBLE);
            if (RunService.failed) {
                status.setVisibility(View.VISIBLE);
                status.setText("Не удалось запустить движок. Закройте и откройте Apply снова. Очередь сохранена.");
            } else if (RunService.ready && !loaded) {
                loaded = true;
                status.setVisibility(View.GONE);
                web.loadUrl(ORIGIN + "/ui/index.html");
            }
            handler.postDelayed(this, 500);
        }
    };
    @Override public void onStart() {
        super.onStart();
        RunService.visible = true;
        startService(new Intent(this, RunService.class));
        handler.post(refresh);
    }
    @Override public void onStop() {
        RunService.visible = false;
        handler.removeCallbacks(refresh);
        super.onStop();
    }
    @Override public void onDestroy() {
        handler.removeCallbacksAndMessages(null);
        web.removeJavascriptInterface("ApplyAndroid");
        web.destroy();
        super.onDestroy();
    }
}
