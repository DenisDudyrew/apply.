package local.apply;

import android.app.NotificationManager;
import android.os.SystemClock;
import androidx.test.core.app.ActivityScenario;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import com.chaquo.python.Python;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

/** Exercise Android's real dataSync time limit, shortened only on the test device. */
@RunWith(AndroidJUnit4.class)
public class BackgroundTimeoutTest {
    private void shell(String command) throws Exception {
        try (var descriptor = InstrumentationRegistry.getInstrumentation().getUiAutomation().executeShellCommand(command);
             var input = new java.io.FileInputStream(descriptor.getFileDescriptor())) { input.readAllBytes(); }
    }
    private void await(java.util.function.BooleanSupplier condition, String message) throws Exception {
        long until = SystemClock.elapsedRealtime() + 30000;
        while (SystemClock.elapsedRealtime() < until) {
            if (condition.getAsBoolean()) return;
            Thread.sleep(200);
        }
        fail(message);
    }
    private JSONObject status() {
        try { return new JSONObject(Python.getInstance().getModule("android_runtime").callAttr("status").toString()); }
        catch (Exception e) { throw new AssertionError(e); }
    }
    @Test public void androidTimeoutStopsServiceWithoutRestartingTheRun() throws Exception {
        var context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        shell("pm grant " + context.getPackageName() + " android.permission.POST_NOTIFICATIONS");
        shell("device_config put activity_manager data_sync_fgs_timeout_duration 3000");
        try (ActivityScenario<MainActivity> activity = ActivityScenario.launch(MainActivity.class)) {
            await(() -> RunService.ready || RunService.failed, "Engine did not start");
            assertFalse(RunService.failed);
            var builtins = Python.getInstance().getBuiltins();
            var globals = builtins.callAttr("dict");
            builtins.callAttr("exec", """
                import ui, hh_apply, hh_auth, time, requests
                _main, _auth, _request = hh_apply.main, hh_auth.status, requests.sessions.Session.request
                hh_auth.status = lambda: {'authenticated': True, 'name': 'Test account'}
                def deny_network(*args, **kwargs):
                    raise AssertionError('Live network forbidden')
                requests.sessions.Session.request = deny_network
                def fake_main(argv, ui, options):
                    ui.progress(phase='pausing')
                    while True:
                        ui.check_stop()
                        time.sleep(.1)
                hh_apply.main = fake_main
                """, globals);
            try {
                String result = RunService.instance.request("/api/action", "{\"action\":\"start\",\"send\":true,\"limit\":2}");
                assertTrue(result, new JSONObject(result).getBoolean("ok"));
                await(() -> status().optBoolean("running"), "Run did not start");
                shell("input keyevent 3");
                await(() -> !status().optBoolean("running"), "Android dataSync timeout did not stop the worker");
                await(() -> RunService.instance == null, "Timed-out service did not stop");
                assertEquals("stopped", status().getString("phase"));
                var manager = context.getSystemService(NotificationManager.class);
                boolean found = false;
                for (var item : manager.getActiveNotifications()) {
                    if (item.getId() == 2) {
                        assertEquals("Android остановил фоновый запуск", item.getNotification().extras.getString("android.title"));
                        found = true;
                        item.getNotification().contentIntent.send();
                    }
                }
                assertTrue("Timeout notice is missing", found);
                await(() -> RunService.ready, "Notice did not reopen the app");
                assertFalse("Run resumed without user action", status().getBoolean("running"));
                JSONObject snapshot = new JSONObject(Python.getInstance().getModule("android_runtime").callAttr("request", "/api/state", "").toString());
                assertTrue(snapshot.getJSONObject("value").getString("message").startsWith("Android остановил"));
            } finally {
                Python.getInstance().getModule("android_runtime").callAttr("stop");
                builtins.callAttr("exec", "hh_apply.main, hh_auth.status, requests.sessions.Session.request = _main, _auth, _request", globals);
            }
        } finally { shell("device_config delete activity_manager data_sync_fgs_timeout_duration"); }
    }
}
