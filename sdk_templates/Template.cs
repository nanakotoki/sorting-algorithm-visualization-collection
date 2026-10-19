// Sorting Visualizer Ultimate —— C# (.NET) 自定义算法模板（单文件）
//
// 说明：.NET 需要「项目 + 源码」才能构建，主程序会自动在缓存目录里生成一个
//       最小 .csproj 再执行 dotnet build / dotnet <exe>，你只需管好本文件。
//
// 手工验证：
//     mkdir -p proj && cp Template.cs proj/Program.cs
//     dotnet new console -o proj --force && dotnet run --project proj < input.txt
//
// 协议（每行一条指令写入 stdout）：
//     CMP i j | CMP_VAL i val | READ i | SWAP i j | SET i val | FLIP l r
//     AUX_INIT size | AUX_SET i val | AUX_GET i | AUX_SWAP i j | AUX_CMP i j | AUX_CLEAR
//     MARK i ROLE | CLEAR_MARKS | MSG text...
//
// 只写你自己的排序逻辑即可，可视化 / 计数器 / 音效全部由指令流自动驱动。

using System;
using System.Collections.Generic;
using System.Globalization;

namespace SortingVisualizerCustom
{
    /// <summary>统一数组包装器（无需修改）。</summary>
    public sealed class VisualArray
    {
        private readonly List<int> _data;
        private List<int> _aux = new List<int>();
        private bool _auxReady;

        public VisualArray(IEnumerable<int> values) { _data = new List<int>(values); }

        public int Size => _data.Count;

        // ---- 内部 --------------------------------------------------------
        private int Check(int i)
        {
            if (i < 0 || i >= _data.Count)
                throw new IndexOutOfRangeException(
                    "索引越界: " + i + "（数组长度 " + _data.Count + "）");
            return i;
        }

        private int CheckAux(int i)
        {
            if (!_auxReady || i < 0 || i >= _aux.Count)
                throw new IndexOutOfRangeException(
                    "辅助数组索引越界: " + i + "（长度 " + _aux.Count + "）");
            return i;
        }

        private static void Emit(string line)
        {
            Console.Out.WriteLine(line);
            Console.Out.Flush();          // 逐行刷新：主程序才能实时渲染
        }

        // ---- 读取 --------------------------------------------------------
        public int Peek(int i) => _data[Check(i)];

        public int Get(int i)             // READ：计 1 次访问
        {
            int k = Check(i);
            Emit("READ " + k);
            return _data[k];
        }

        // ---- 比较 --------------------------------------------------------
        public bool Cmp(int i, int j)     // arr[i] < arr[j]
        {
            int a = Check(i), b = Check(j);
            Emit("CMP " + a + " " + b);
            return _data[a] < _data[b];
        }

        public bool Gt(int i, int j)      // arr[i] > arr[j]（严格）
        {
            int a = Check(i), b = Check(j);
            Emit("CMP " + b + " " + a);
            return _data[a] > _data[b];
        }

        public bool CmpVal(int i, int val) // arr[i] < val
        {
            int a = Check(i);
            Emit("CMP_VAL " + a + " " + val);
            return _data[a] < val;
        }

        public bool GtVal(int i, int val)  // arr[i] > val
        {
            int a = Check(i);
            Emit("CMP_VAL " + a + " " + val);
            return _data[a] > val;
        }

        // ---- 写入 --------------------------------------------------------
        public void Swap(int i, int j)
        {
            int a = Check(i), b = Check(j);
            if (a == b) return;
            Emit("SWAP " + a + " " + b);
            int t = _data[a]; _data[a] = _data[b]; _data[b] = t;
        }

        public void Set(int i, int val)
        {
            int a = Check(i);
            Emit("SET " + a + " " + val);
            _data[a] = val;
        }

        public void Flip(int left, int right)   // 原地翻转 [left, right]
        {
            int l = Check(left), r = Check(right);
            if (l >= r) return;
            Emit("FLIP " + l + " " + r);
            while (l < r)
            {
                int t = _data[l]; _data[l] = _data[r]; _data[r] = t;
                l++; r--;
            }
        }

        // ---- 辅助数组 ----------------------------------------------------
        public void AuxInit(int size)
        {
            int m = size < 0 ? 0 : size;
            Emit("AUX_INIT " + m);
            _aux = new List<int>(new int[m]);
            _auxReady = true;
        }

        public void AuxSet(int i, int val)
        {
            int k = CheckAux(i);
            Emit("AUX_SET " + k + " " + val);
            _aux[k] = val;
        }

        public int AuxGet(int i)
        {
            int k = CheckAux(i);
            Emit("AUX_GET " + k);
            return _aux[k];
        }

        public void AuxSwap(int i, int j)
        {
            int a = CheckAux(i), b = CheckAux(j);
            if (a == b) return;
            Emit("AUX_SWAP " + a + " " + b);
            int t = _aux[a]; _aux[a] = _aux[b]; _aux[b] = t;
        }

        public bool AuxCmp(int i, int j)
        {
            int a = CheckAux(i), b = CheckAux(j);
            Emit("AUX_CMP " + a + " " + b);
            return _aux[a] < _aux[b];
        }

        public void AuxClear()
        {
            Emit("AUX_CLEAR");
            _aux = new List<int>();
            _auxReady = false;
        }

        // ---- 标记与解说 --------------------------------------------------
        public void Mark(int i, string role)
        {
            int k = Check(i);
            Emit("MARK " + k + " " + role.ToUpperInvariant());
        }

        public void ClearMarks() => Emit("CLEAR_MARKS");

        public void Msg(string text) => Emit("MSG " + text);

        public bool IsSorted()
        {
            for (int i = 1; i < _data.Count; i++)
                if (_data[i - 1] > _data[i]) return false;
            return true;
        }
    }

    public static class Program
    {
        /* =================================================================
         * ★ 在这里编写你的排序算法 ★（下面是一个可跑通的示例：插入排序）
         * ================================================================= */
        public static void MyCustomSort(VisualArray arr, int n)
        {
            for (int i = 1; i < n; i++)
            {
                int j = i;
                arr.Mark(j, "CURSOR");
                while (j > 0 && arr.Gt(j - 1, j))     // arr[j-1] > arr[j] 才交换
                {
                    arr.Swap(j - 1, j);
                    j--;
                }
                arr.Mark(j, "SORTED");
            }
            arr.ClearMarks();
        }

        /* =================================================================
         * 输入输出（无需修改）
         * ================================================================= */
        private static Tuple<int, List<int>> ReadInput()
        {
            string raw = Console.In.ReadToEnd();
            var tokens = raw.Split((char[])null,
                                   StringSplitOptions.RemoveEmptyEntries);
            if (tokens.Length == 0) return Tuple.Create(0, new List<int>());
            int n;
            if (!int.TryParse(tokens[0], NumberStyles.Integer,
                              CultureInfo.InvariantCulture, out n))
                throw new FormatException("N 不是整数: " + tokens[0]);
            if (n < 0) n = 0;
            var values = new List<int>(n);
            for (int k = 1; k <= n; k++)
            {
                if (k >= tokens.Length)
                    throw new FormatException("数组元素不足 " + n + " 个");
                int v;
                if (!int.TryParse(tokens[k], NumberStyles.Integer,
                                  CultureInfo.InvariantCulture, out v))
                    throw new FormatException("第 " + k + " 个元素不是整数: " + tokens[k]);
                values.Add(v);
            }
            return Tuple.Create(n, values);
        }

        public static int Main()
        {
            // 统一按 UTF-8 输出，避免中文 MSG 在 Windows 控制台代码页下变乱码
            try
            {
                Console.OutputEncoding = new System.Text.UTF8Encoding(false);
            }
            catch (Exception)
            {
                // 无控制台或不允许设置时忽略
            }

            int n;
            List<int> values;
            try
            {
                var input = ReadInput();
                n = input.Item1;
                values = input.Item2;
            }
            catch (Exception e)
            {
                Console.Error.WriteLine("输入解析失败: " + e.Message);
                return 2;
            }

            var arr = new VisualArray(values);
            try
            {
                MyCustomSort(arr, n);
            }
            catch (Exception e)
            {
                arr.Msg("自定义算法异常：" + e.GetType().Name + ": " + e.Message);
                Console.Error.WriteLine(e);
                return 1;
            }

            if (arr.IsSorted())
                arr.Msg("自定义算法完成：数组已有序 ✓");
            else
            {
                arr.Msg("自定义算法结束：数组尚未有序 ✗");
                Console.Error.WriteLine("警告：算法返回时数组并未有序");
            }
            Console.Out.Flush();
            return 0;
        }
    }
}
