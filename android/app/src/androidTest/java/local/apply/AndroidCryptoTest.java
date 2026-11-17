package local.apply;

import android.util.Base64;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import java.security.KeyPairGenerator;
import java.security.spec.MGF1ParameterSpec;
import java.nio.charset.StandardCharsets;
import javax.crypto.Cipher;
import javax.crypto.spec.OAEPParameterSpec;
import javax.crypto.spec.PSource;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
public class AndroidCryptoTest {
    @Test public void loginEncryptionUsesSha256ForBothOaepAndMgf1() throws Exception {
        var generator = KeyPairGenerator.getInstance("RSA");
        generator.initialize(2048);
        var pair = generator.generateKeyPair();
        String pem = "-----BEGIN PUBLIC KEY-----\n" + Base64.encodeToString(pair.getPublic().getEncoded(), Base64.NO_WRAP) + "\n-----END PUBLIC KEY-----";
        String payload = "{\"ts\":123,\"emailOrPhone\":{\"paste\":false}}";
        byte[] ciphertext = Base64.decode(SecretVault.encryptLogin(pem, payload), Base64.NO_WRAP);
        var cipher = Cipher.getInstance("RSA/ECB/OAEPPadding");
        cipher.init(Cipher.DECRYPT_MODE, pair.getPrivate(), new OAEPParameterSpec("SHA-256", "MGF1", MGF1ParameterSpec.SHA256, PSource.PSpecified.DEFAULT));
        assertEquals(payload, new String(cipher.doFinal(ciphertext), StandardCharsets.UTF_8));
    }
    @Test public void accountTokenIsEncryptedAndSurvivesNewVaultInstance() throws Exception {
        var context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        var vault = new SecretVault(context);
        String previous = vault.read();
        try {
            String value = "{\"access_token\":\"instrumentation-only-token\"}";
            vault.write(value);
            assertEquals(value, new SecretVault(context).read());
            String stored = context.getSharedPreferences("account", 0).getString("ciphertext", "");
            assertFalse(stored.contains("instrumentation-only-token"));
            vault.write("{}");
            assertEquals("{}", vault.read());
        } finally { vault.write(previous); }
    }
}
