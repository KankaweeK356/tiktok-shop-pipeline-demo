Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
using System.Text;

public class GitCredPusher {
    [DllImport("advapi32.dll", EntryPoint = "CredReadW", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern bool CredRead(string target, int type, int reservedFlag, out IntPtr credentialPtr);

    [DllImport("advapi32.dll", SetLastError = true)]
    public static extern void CredFree(IntPtr credentialPtr);

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct CREDENTIAL {
        public int Flags;
        public int Type;
        public string TargetName;
        public string Comment;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastWritten;
        public int CredentialBlobSize;
        public IntPtr CredentialBlob;
        public int Persist;
        public int AttributeCount;
        public IntPtr Attributes;
        public string TargetAlias;
        public string UserName;
    }

    public static string GetSecretUtf8(string target) {
        IntPtr credPtr;
        if (CredRead(target, 1, 0, out credPtr)) {
            CREDENTIAL cred = (CREDENTIAL)Marshal.PtrToStructure(credPtr, typeof(CREDENTIAL));
            byte[] bytes = new byte[cred.CredentialBlobSize];
            Marshal.Copy(cred.CredentialBlob, bytes, 0, cred.CredentialBlobSize);
            CredFree(credPtr);
            return Encoding.UTF8.GetString(bytes);
        }
        return null;
    }
}
"@

$token = [GitCredPusher]::GetSecretUtf8("LegacyGeneric:target=GitHub - https://api.github.com/KankaweeK356")
if (-not $token) {
    $token = [GitCredPusher]::GetSecretUtf8("GitHub - https://api.github.com/KankaweeK356")
}
if (-not $token) {
    Write-Error "Could not retrieve GitHub token from Windows Credential Manager"
    exit 1
}

$gitExe = "C:\Users\kankawee.k\AppData\Local\GitHubDesktop\app-3.6.11\resources\app\git\cmd\git.exe"
& $gitExe add api/lab-batch.js api/lab-batch-result.js dashboard/app.js
& $gitExe commit -m "fix(pipeline): resolve February stage waiting state, decouple execution vs viewed month, add canonical batch hydration, and data-driven decision rules"
$pushUrl = "https://x-access-token:$token@github.com/KankaweeK356/tiktok-shop-pipeline-demo.git"
& $gitExe push $pushUrl feature/classroom-demo-evidence-foundation
