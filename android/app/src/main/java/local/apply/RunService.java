package local.apply;

import android.app.*;
import android.content.*;
import android.content.pm.ServiceInfo;
import android.net.Uri;
import android.os.*;
import com.chaquo.python.Python;
import com.chaquo.python.PyObject;
import com.chaquo.python.android.AndroidPlatform;
import org.json.JSONObject;
import java.util.concurrent.*;

public class RunService extends Service {
    static volatile RunService instance;
    static volatile boolean visible;
    static volatile boolean ready;
    static volatile boolean failed;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService engine = Executors.newSingleThreadExecutor();
    private volatile PyObject runtime;
    private SecretVault vault;
    private PowerManager.WakeLock wake;
    private boolean foreground;
    private boolean destroyed;
    private volatile boolean timedOut;
    private long graceUntil;
    private long idleSince;
    private long wakeRenewedAt;
    private String lastProgress = "";
    private static final String PROGRESS = "run_progress", ATTENTION = "attention";

    @Override public void onCreate() {
        super.onCreate();
        instance = this;
        ready = false; failed = false;
        vault = new SecretVault(this);
        var manager = getSystemService(NotificationManager.class);
        manager.createNotificationChannel(new NotificationChannel(PROGRESS, "Ход запуска", NotificationManager.IMPORTANCE_LOW));
        manager.createNotificationChannel(new NotificationChannel(ATTENTION, "Капча и результат запуска", NotificationManager.IMPORTANCE_HIGH));
        wake = ((PowerManager)getSystemService(POWER_SERVICE)).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "Apply:run");
        wake.setReferenceCounted(false);
        engine.submit(() -> {
            try {
                if (!Python.isStarted()) Python.start(new AndroidPlatform(this));
                runtime = Python.getInstance().getModule("android_runtime");
                runtime.callAttr("initialize", this, getFilesDir().getAbsolutePath());
                ready = true;
            } catch (Exception e) {
                android.util.Log.e("Apply", "Engine startup failed", e);
                failed = true;
            }
            main.post(tick);
        });
    }

    @Override public int onStartCommand(Intent intent, int flags, int id) {
        if (intent != null && "STOP".equals(intent.getAction())) stopWork();
        return START_NOT_STICKY; // No automatic sending after OS kill/reboot.
    }
    @Override public IBinder onBind(Intent intent) { return null; }

    private PendingIntent openIntent() {
        return PendingIntent.getActivity(this, 0, new Intent(this, MainActivity.class)
            .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP), PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
    }
    private Notification progress(String text) {
        PendingIntent stop = PendingIntent.getService(this, 1, new Intent(this, RunService.class).setAction("STOP"), PendingIntent.FLAG_IMMUTABLE);
        return new Notification.Builder(this, PROGRESS).setSmallIcon(local.apply.R.drawable.ic_notice)
            .setContentTitle("Apply · запуск выполняется").setContentText(text).setContentIntent(openIntent())
            .setOngoing(true).setOnlyAlertOnce(true).setVisibility(Notification.VISIBILITY_PRIVATE)
            .addAction(new Notification.Action.Builder(null, "Остановить", stop).build()).build();
    }
    public void notice(String title, String text) {
        if (timedOut && !title.equals("Android остановил фоновый запуск")) return;
        Runnable show = () -> {
            if (destroyed) return;
            Notification notification = new Notification.Builder(this, ATTENTION).setSmallIcon(local.apply.R.drawable.ic_notice)
                .setContentTitle(title).setContentText(text).setStyle(new Notification.BigTextStyle().bigText(text))
                .setContentIntent(openIntent()).setAutoCancel(true).setVisibility(Notification.VISIBILITY_PRIVATE).build();
            getSystemService(NotificationManager.class).notify(2, notification);
        };
        if (Looper.myLooper() == Looper.getMainLooper()) show.run(); else main.post(show);
    }
    public void beginWork() throws Exception {
        if (!visible || destroyed || !ready) throw new IllegalStateException("Откройте Apply перед запуском.");
        if (!getSystemService(NotificationManager.class).areNotificationsEnabled())
            throw new IllegalStateException("Разрешите уведомления Apply перед запуском.");
        var task = new FutureTask<Void>(() -> {
            graceUntil = SystemClock.elapsedRealtime() + 10000;
            startForeground(1, progress("Подготовка…"), ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
            foreground = true;
            if (!wake.isHeld()) wake.acquire(10 * 60 * 1000L);
            wakeRenewedAt = SystemClock.elapsedRealtime();
            return null;
        });
        if (Looper.myLooper() == Looper.getMainLooper()) task.run(); else main.post(task);
        task.get(5, TimeUnit.SECONDS);
    }
    public String readSecret() throws Exception { return vault.read(); }
    public void writeSecret(String value) throws Exception { vault.write(value); }
    public String encryptLogin(String pem, String value) throws Exception { return SecretVault.encryptLogin(pem, value); }
    public void openExternal(String value) {
        Uri uri = Uri.parse(value);
        String host = uri.getHost();
        if (!"https".equals(uri.getScheme()) || host == null || !(host.equals("hh.ru") || host.endsWith(".hh.ru") || host.equals("github.com"))) return;
        main.post(() -> { try { startActivity(new Intent(Intent.ACTION_VIEW, uri).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)); } catch (ActivityNotFoundException ignored) {} });
    }
    public void openBatterySettings() {
        main.post(() -> startActivity(new Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
            Uri.parse("package:" + getPackageName())).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)));
    }
    public String request(String path, String body) {
        if (!ready || runtime == null || destroyed) return "{\"ok\":false,\"error\":\"Движок ещё запускается.\"}";
        if (path.equals("/api/action") && body.contains("\"action\"")) {
            try {
                String action = new JSONObject(body).optString("action");
                if (java.util.Set.of("start", "resume_queue", "login", "load_resumes").contains(action)
                    && !getSystemService(NotificationManager.class).areNotificationsEnabled()) {
                    return "{\"ok\":false,\"error\":\"Разрешите уведомления Apply в настройках Android перед запуском.\"}";
                }
            } catch (Exception ignored) {}
        }
        try { return runtime.callAttr("request", path, body).toString(); }
        catch (Exception e) { return "{\"ok\":false,\"error\":\"Не удалось связаться с движком. Перезапустите Apply.\"}"; }
    }
    private void stopWork() {
        if (runtime != null) runtime.callAttr("stop");
    }
    private final Runnable tick = new Runnable() {
        @Override public void run() {
            if (destroyed) return;
            if (ready && runtime != null) {
                // Database/API operations never run on the Android UI thread.
                engine.submit(() -> {
                    try {
                        JSONObject state = new JSONObject(runtime.callAttr("status").toString());
                        main.post(() -> update(state));
                    } catch (Exception e) { main.post(() -> { failed = true; stopWork(); }); }
                });
            }
            main.postDelayed(this, 2000);
        }
    };
    private void update(JSONObject state) {
        if (destroyed) return;
        boolean busy = state.optBoolean("running") || SystemClock.elapsedRealtime() < graceUntil;
        if (busy) {
            idleSince = 0;
            if (foreground) {
                if (!wake.isHeld() || SystemClock.elapsedRealtime() - wakeRenewedAt > 5 * 60 * 1000L) {
                    wake.acquire(10 * 60 * 1000L);
                    wakeRenewedAt = SystemClock.elapsedRealtime();
                }
                String phase = state.optString("phase");
                String text = state.optBoolean("waiting") ? "Нужен ваш ответ — нажмите, чтобы открыть Apply" :
                    phase.equals("captcha_wait") ? "Капча: ожидаем проверки. Можно заполнить сейчас." :
                    "Подтверждено откликов: " + state.optInt("sent") + " / " + state.optInt("limit");
                if (!text.equals(lastProgress)) { lastProgress = text; getSystemService(NotificationManager.class).notify(1, progress(text)); }
            }
        } else {
            if (foreground) { stopForeground(STOP_FOREGROUND_REMOVE); foreground = false; lastProgress = ""; }
            if (wake.isHeld()) wake.release();
            if (!visible) {
                if (idleSince == 0) idleSince = SystemClock.elapsedRealtime();
                if (SystemClock.elapsedRealtime() - idleSince > 5000) stopSelf();
            } else idleSince = 0;
        }
    }
    @Override public void onTimeout(int startId, int type) {
        timedOut = true;
        if (runtime != null) runtime.callAttr("stop", "Android остановил фоновый запуск. Проверьте историю и продолжите сохранённую очередь вручную.");
        notice("Android остановил фоновый запуск", "Очередь сохранена. Откройте Apply и проверьте результат перед продолжением.");
        stopForeground(STOP_FOREGROUND_REMOVE);
        foreground = false;
        stopSelf();
    }
    @Override public void onDestroy() {
        destroyed = true;
        main.removeCallbacksAndMessages(null);
        stopWork();
        if (wake.isHeld()) wake.release();
        ready = false;
        if (instance == this) instance = null;
        engine.shutdown();
        super.onDestroy();
    }
}
