using Confluent.Kafka;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace Patient_Management_System.Kafka
{
    public class KafkaProducer
    {
        private readonly IProducer<Null, string> _producer;

        public KafkaProducer(IConfiguration config)
        {
            var producerConfig = new ProducerConfig
            {
                BootstrapServers = config["Kafka:BootstrapServers"]
            };

            _producer = new ProducerBuilder<Null, string>(producerConfig).Build();
        }

        public async Task PublishAsync(string topic, object message, CancellationToken cancellationToken = default)
        {
            var json = JsonSerializer.Serialize(message);

            await _producer.ProduceAsync(topic, new Message<Null, string>
            {
                Value = json
            }, cancellationToken);
        }
    }
}