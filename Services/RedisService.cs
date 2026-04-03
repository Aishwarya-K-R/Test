using StackExchange.Redis;

namespace Patient_Management_System.Services
{
    public class RedisService(IConnectionMultiplexer redis, IConfiguration config)
    {
        private readonly IDatabase _db = redis.GetDatabase();
        private readonly string _updatedPatientsKey = config["RedisKeys:UpdatedPatientsKey"];

        public async Task MarkUpdatedAsync(int patientId)
        {
            await _db.SetAddAsync(_updatedPatientsKey, patientId);
        }

        public async Task ClearPatientContextAsync(int patientId)
        {
            await _db.KeyDeleteAsync($"patient-context:{patientId}");
            await _db.SetRemoveAsync(_updatedPatientsKey, patientId);
        }

        public async Task<List<int>> GetUpdatedPatientsAsync()
        {
            var values = await _db.SetMembersAsync(_updatedPatientsKey);
            return values.Select(v => (int)v).ToList();
        }

        public async Task ClearUpdatedPatientsAsync()
        {
            await _db.KeyDeleteAsync(_updatedPatientsKey);
        }

        public async Task SetPatientContextAsync(int patientId, string context)
        {
            await _db.StringSetAsync($"patient-context:{patientId}", context);
        }

        public async Task<Dictionary<int, string>> GetAllPatientContextsAsync()
        {
            var server = _db.Multiplexer.GetServer(_db.Multiplexer.GetEndPoints()[0]);
            var keys = server.Keys(pattern: "patient-context:*").ToArray();

            var dict = new Dictionary<int, string>();
            foreach (var key in keys)
            {
                var value = await _db.StringGetAsync(key);
                if (!string.IsNullOrEmpty(value))
                {
                    int id = int.Parse(key.ToString().Split(":")[1]);
                    dict[id] = value;
                }
            }
            return dict;
        }
    }
}