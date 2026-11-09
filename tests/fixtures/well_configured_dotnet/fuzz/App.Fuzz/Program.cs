using SharpFuzz;

namespace App.Fuzz;

public static class Program
{
    public static void Main() => Fuzzer.LibFuzzer.Run(data => Calculator.Add(data.Length, data.Length));
}
