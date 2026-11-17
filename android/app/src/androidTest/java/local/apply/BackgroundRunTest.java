package local.apply;

import android.app.NotificationManager;
import android.content.Intent;
import android.os.SystemClock;
import androidx.test.core.app.ActivityScenario;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import com.chaquo.python.Python;
import com.chaquo.python.PyObject;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import java.util.function.BooleanSupplier;
import static org.junit.Assert.*;

/** Real Android service/notification checks, using a fake account and zero HH requests. */
@RunWith(AndroidJUnit4.class)
public class BackgroundRunTest {
    private void await(BooleanSupplier condition, String message) throws Exception {
        long until = SystemClock.elapsedRealtime() + 30000;
        while (SystemClock.elapsedRealtime() < until) {
            if (condition.getAsBoolean()) return;
            Thread.sleep(200);
        }
        fail(message);
    }
    private JSONObject state() {
        try { return new JSONObject(Python.getInstance().getModule("android_runtime").callAttr("status").toString()); }
        catch (Exception e) { throw new AssertionError(e); }
    }
    @Test public void runSurvivesHomeAndScreenOffAndStopsFromNotification() throws Exception {
        var instrumentation = InstrumentationRegistry.getInstrumentation();
        var context = instrumentation.getTargetContext();
        instrumentation.getUiAutomation().executeShellCommand("pm grant " + context.getPackageName() + " android.permission.POST_NOTIFICATIONS").close();
        await(() -> context.checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) == android.content.pm.PackageManager.PERMISSION_GRANTED,
            "Notification permission was not granted");
        try (ActivityScenario<MainActivity> activity = ActivityScenario.launch(MainActivity.class)) {
            await(() -> RunService.ready || RunService.failed, "Engine startup timed out");
            assertFalse("Embedded Python engine failed to start", RunService.failed);
            PyObject builtins = Python.getInstance().getBuiltins();
            PyObject globals = builtins.callAttr("dict");
            builtins.callAttr("exec", """
                import ui, hh_apply, hh_auth, time, requests
                _real_main, _real_status, _real_request = hh_apply.main, hh_auth.status, requests.sessions.Session.request
                def _deny_network(*args, **kwargs):
                    raise AssertionError('Live network forbidden in Android instrumentation')
                requests.sessions.Session.request = _deny_network
                hh_auth.status = lambda: {'authenticated': True, 'name': 'Test account'}
                def _fake_main(argv, ui, options):
                    ui.progress(sent=1, total=3, phase='sending')
                    ui.prompt('Тестовая капча: откройте Apply')
                    ui.progress(phase='pausing')
                    until = time.monotonic() + 4
                    while time.monotonic() < until:
                        ui.check_stop()
                        time.sleep(.1)
                    ui.progress(sent=2)
                    while True:
                        ui.check_stop()
                        time.sleep(.1)
                hh_apply.main = _fake_main
                """, globals);
            try {
                JSONObject result = new JSONObject(RunService.instance.request("/api/action", "{\"action\":\"start\",\"send\":true,\"limit\":3}"));
                assertTrue(result.toString(), result.getBoolean("ok"));
                await(() -> state().optBoolean("waiting"), "CAPTCHA prompt did not appear");
                var manager = context.getSystemService(NotificationManager.class);
                await(() -> manager.getActiveNotifications().length >= 2, "Progress and CAPTCHA notifications missing");
                await(() -> java.util.Arrays.stream(manager.getActiveNotifications()).anyMatch(item ->
                    item.getId() == 2 && "Apply ждёт вашего ответа".equals(item.getNotification().extras.getString("android.title"))),
                    "CAPTCHA attention notification is missing");
                instrumentation.getUiAutomation().executeShellCommand("input keyevent 3").close();
                await(() -> !RunService.visible, "Activity did not move to the background");
                instrumentation.getUiAutomation().executeShellCommand("input keyevent 223").close();
                Thread.sleep(5000);
                assertTrue("Run stopped while app was hidden", state().getBoolean("running"));
                assertEquals(1, state().getInt("sent"));
                assertNotNull("Foreground service disappeared", RunService.instance);
                instrumentation.getUiAutomation().executeShellCommand("input keyevent 224").close();
                instrumentation.getUiAutomation().executeShellCommand("wm dismiss-keyguard").close();
                for (var notice : manager.getActiveNotifications()) {
                    if (notice.getId() == 2) notice.getNotification().contentIntent.send();
                }
                await(() -> RunService.visible, "Notification did not reopen Apply");
                PyObject runtime = Python.getInstance().getModule("android_runtime");
                JSONObject session = new JSONObject(runtime.callAttr("request", "/api/session", "").toString());
                String prompt = session.getJSONObject("value").getJSONObject("state").getString("prompt_id");
                RunService.instance.request("/api/action", new JSONObject().put("action", "answer").put("text", "test").put("prompt_id", prompt).toString());
                await(() -> !state().optBoolean("waiting"), "CAPTCHA answer did not reach the worker");
                instrumentation.getUiAutomation().executeShellCommand("input keyevent 3").close();
                await(() -> !RunService.visible, "Activity did not return to the background");
                instrumentation.getUiAutomation().executeShellCommand("input keyevent 223").close();
                await(() -> state().optInt("sent") == 2, "Python worker did not advance with the screen off");
                instrumentation.getUiAutomation().executeShellCommand("input keyevent 224").close();
                instrumentation.getUiAutomation().executeShellCommand("wm dismiss-keyguard").close();
                for (var notice : manager.getActiveNotifications()) {
                    if (notice.getId() == 1) notice.getNotification().actions[0].actionIntent.send();
                }
                await(() -> !state().optBoolean("running"), "Stop button did not stop the worker");
                assertEquals("stopped", state().getString("phase"));
            } finally {
                Python.getInstance().getModule("android_runtime").callAttr("stop");
                builtins.callAttr("exec", "hh_apply.main, hh_auth.status, requests.sessions.Session.request = _real_main, _real_status, _real_request", globals);
            }
        }
    }
}
